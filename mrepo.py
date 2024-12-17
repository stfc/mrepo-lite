#!/usr/bin/python2

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU Library General Public License as published by
### the Free Software Foundation; version 2 only
###
### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU Library General Public License for more details.
###
### You should have received a copy of the GNU Library General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
### Copyright 2004-2007 Dag Wieers <dag@wieers.com>

import ConfigParser
import getopt
import glob
import os
from os.path import exists as path_exists
from os.path import isdir as path_is_dir
from os.path import join as path_join

import re
import tempfile

from hashlib import sha1 as sha1hash

import shutil
import smtplib
import sys
import time
import types
import urlparse
import urllib

__version__ = "#version#"

VERSION = __version__

ARCHS = {
    'alpha': ('alpha', 'alphaev5', 'alphaev56', 'alphaev6', 'alphaev67'),
    'i386': ('i386', 'i486', 'i586', 'i686', 'athlon'),
    'ia64': ('i386', 'i686', 'ia64'),
    'ppc': ('ppc', ),
    'ppc64': ('ppc', 'ppc64', 'ppc64pseries', 'ppc64iseries'),
    'x86_64': ('i386', 'i486', 'i586', 'i686', 'athlon', 'x86_64', 'amd64', 'ia32e'),
    'sparc64': ('sparc', 'sparcv8', 'sparcv9', 'sparc64'),
    'sparc64v': ('sparc', 'sparcv8', 'sparcv9', 'sparcv9v', 'sparc64', 'sparc64v'),
    's390': ('s390', ),
    's390x': ('s390', 's390x'),
}

VARIABLES = {}

DISABLE = ('no', 'off', 'false', '0')

EXITCODE = 0

_SUBST_SUB = re.compile(r'\$\{?(\w+)\}?').sub


class Options(object):
    def __init__(self, args):
        self.configfile = '/etc/mrepo.conf'
        self.dists = []
        self.force = False
        self.dryrun = False
        self.generate = False
        self.quiet = False
        self.repos = []
        self.types = []
        self.update = False
        self.verbose = 1
        self.create_aggregate_repos = False

        try:
            opts, args = getopt.getopt(args, 'c:d:fghnqr:t:uvx', (
                'config=',
                'dist=',
                'dry-run',
                'force',
                'generate',
                'help',
                'quiet',
                'repo=',
                'type=',
                'update',
                'verbose',
                'version',
                'extras',
            ))
        except getopt.error as instance:
            print 'mrepo: %s, try mrepo -h for a list of all the options' % str(instance)
            sys.exit(1)

        for opt, arg in opts:
            if opt in ('-c', '--config'):
                self.configfile = os.path.abspath(arg)
            elif opt in ('-d', '--dist'):
                print 'mrepo: the use of -d or --dist as an option is deprecated, use the argument list'
                self.dists = self.dists + arg.split(',')
            elif opt in ('-f', '--force'):
                self.force = True
            elif opt in ('-g', '--generate'):
                self.generate = True
            elif opt in ('-h', '--help'):
                self.usage()
                print
                self.help()
                sys.exit(0)
            elif opt in ('-n', '--dry-run'):
                self.dryrun = True
            elif opt in ('-q', '--quiet'):
                self.quiet = True
            elif opt in ('-r', '--repo'):
                self.repos = self.repos + arg.split(',')
            elif opt in ('-t', '--type'):
                self.types = self.types + arg.split(',')
            elif opt in ('-u', '--update'):
                self.update = True
            elif opt in ('-v', '--verbose'):
                self.verbose = self.verbose + 1
            elif opt in ('--version', ):
                self.version()
                sys.exit(0)
            elif opt in ('-x', '--extras'):
                print 'mrepo: the use of -x or --extras is deprecated, use -u and -r instead'
                self.update = True

        if not self.types:
            self.types = ['fish', 'ftp', 'http', 'https',
                          'rsync', 'sftp', 'reposync', 'reposyncs',
                          'reposyncf']

        for arg in args:
            self.dists = self.dists + arg.split(',')

        if self.quiet:
            self.verbose = 0

        if self.verbose >= 3:
            print 'Verbosity set to level %d' % (self.verbose - 1)
            print 'Using configfile %s' % self.configfile

    def version(self):
        print 'mrepo %s' % VERSION
        print 'Written by Dag Wieers <dag@wieers.com>'
        print 'Homepage at http://dag.wieers.com/home-made/mrepo/'
        print
        print 'platform %s/%s' % (os.name, sys.platform)
        print 'python %s' % sys.version
        print
        print 'build revision $Rev$'

    def usage(self):
        print 'usage: mrepo [options] dist1 [dist2-arch ..]'

    def help(self):
        print '''Set up a mirror server

mrepo options:
  -c, --config=file       specify alternative configfile
  -f, --force             force repository generation
  -g, --generate          generate mrepo repositories
  -n, --dry-run           show what would have been done
  -q, --quiet             minimal output
  -r, --repo=repo1,repo2  restrict action to specific repositories
  -t, --type=type1,type2  mirror types to use. Default: fish, ftp, http, https, rsync, sftp
  -u, --update            fetch OS updates
  -v, --verbose           increase verbosity
      --version           print mrepo version information
  -vv, -vvv, -vvvv..      increase verbosity more
'''


class Config(object):
    def __init__(self):
        self.read(OPTIONS.configfile)

        self.cachedir = self.getoption('main', 'cachedir', '/var/cache/mrepo')
        self.lockdir = self.getoption('main', 'lockdir', '/var/cache/mrepo')
        self.confdir = self.getoption('main', 'confdir', '/etc/mrepo.conf.d')
        self.srcdir = self.getoption('main', 'srcdir', '/var/mrepo')
        self.wwwdir = self.getoption('main', 'wwwdir', '/var/www/mrepo')
        self.logfile = self.getoption('main', 'logfile', '/var/log/mrepo.log')

        self.mailto = self.getoption('main', 'mailto', None)
        self.mailfrom = self.getoption('main', 'mailfrom', 'mrepo@%s' % os.uname()[1])
        self.smtpserver = self.getoption('main', 'smtp-server', 'localhost')

        self.arch = self.getoption('main', 'arch', 'i386')
        self.metadata = self.getoption('main', 'metadata', 'repomd')

        self.quiet = self.getoption('main', 'quiet', 'no') not in DISABLE
        if OPTIONS.verbose == 1 and self.quiet:
            OPTIONS.verbose = 0

        self.no_proxy = self.getoption('main', 'no_proxy', None)
        self.ftp_proxy = self.getoption('main', 'ftp_proxy', None)
        self.http_proxy = self.getoption('main', 'http_proxy', None)
        self.https_proxy = self.getoption('main', 'https_proxy', None)
        self.rsync_proxy = self.getoption('main', 'RSYNC_PROXY', None)

        self.cmd = {}
        self.cmd['createrepo'] = self.getoption('main', 'createrepocmd', '/usr/bin/createrepo')
        self.cmd['lftp'] = self.getoption('main', 'lftpcmd', '/usr/bin/lftp')
        self.cmd['reposync'] = self.getoption('main', 'reposynccmd', '/usr/bin/reposync')
        self.cmd['rsync'] = self.getoption('main', 'rsynccmd', '/usr/bin/rsync')

        self.createrepooptions = self.getoption('main', 'createrepo-options', '--pretty --database --update')

        self.lftpbwlimit = self.getoption('main', 'lftp-bandwidth-limit', None)
        self.lftpcleanup = self.getoption('main', 'lftp-cleanup', 'yes') not in DISABLE
        self.lftpexcldebug = self.getoption('main', 'lftp-exclude-debug', 'yes') not in DISABLE
        self.lftpexclsrpm = self.getoption('main', 'lftp-exclude-srpm', 'yes') not in DISABLE
        self.lftpoptions = self.getoption('main', 'lftp-options', '')
        self.lftpcommands = self.getoption('main', 'lftp-commands', '')
        self.lftpmirroroptions = self.getoption('main', 'lftp-mirror-options', '-c')
        self.lftptimeout = self.getoption('main', 'lftp-timeout', None)

        self.reposyncoptions = self.getoption('main', 'reposync-options', '')
        self.reposynccleanup = self.getoption('main', 'reposync-cleanup', 'yes') not in DISABLE
        self.reposyncnewestonly = self.getoption('main', 'reposync-newest-only', 'no') not in DISABLE
        self.reposyncexcldebug = self.getoption('main', 'reposync-exclude-debug', 'yes') not in DISABLE
        self.reposyncnorepopath = self.getoption('main', 'reposync-no-repopath', 'yes') not in DISABLE
        self.reposynctimeout = self.getoption('main', 'reposync-timeout', '90')
        self.reposyncminrate = self.getoption('main', 'reposync-minrate', '250')

        self.rsyncbwlimit = self.getoption('main', 'rsync-bandwidth-limit', None)
        self.rsynccleanup = self.getoption('main', 'rsync-cleanup', 'yes') not in DISABLE
        self.rsyncexclheaders = self.getoption('main', 'rsync-exclude-headers', 'yes') not in DISABLE
        self.rsyncexclrepodata = self.getoption('main', 'rsync-exclude-repodata', 'yes') not in DISABLE
        self.rsyncexcldebug = self.getoption('main', 'rsync-exclude-debug', 'yes') not in DISABLE
        self.rsyncexclsrpm = self.getoption('main', 'rsync-exclude-srpm', 'yes') not in DISABLE
        self.rsyncoptions = self.getoption('main', 'rsync-options', '-rtHL --partial')
        self.rsynctimeout = self.getoption('main', 'rsync-timeout', None)

        self.alldists = []
        self.dists = []

        self.update()

    def read(self, configfile):
        self.cfg = ConfigParser.ConfigParser()

        info(4, 'Reading config file %s' % (configfile))

        urlscheme = urlparse.urlparse(configfile)[0]
        if urlscheme in ('http', 'ftp', 'file'):
            configfh = urllib.urlopen(configfile)
            try:
                self.cfg.readfp(configfh)
            except IOError:
                die(6, 'Error accessing URL: %s' % configfile)
        else:
            if os.access(configfile, os.R_OK):
                try:
                    self.cfg.read(configfile)
                except ConfigParser.MissingSectionHeaderError:
                    die(7, 'Syntax error reading file: %s' % configfile)
            else:
                die(6, 'Error accessing file: %s' % configfile)

    def update(self):
        for section in ('variables', 'vars', 'DEFAULT'):
            if section in self.cfg.sections():
                for option in self.cfg.options(section):
                    VARIABLES[option] = self.cfg.get(section, option)

        for section in self.cfg.sections():
            if section in ('main', 'repos', 'variables', 'vars', 'DEFAULT'):
                continue
            else:
                ### Check if section has appended arch
                for arch in ARCHS:
                    if section.endswith('-%s' % arch):
                        archlist = (arch,)
                        distname = section.split('-%s' % arch)[0]
                        break
                else:
                    archlist = self.getoption(section, 'arch', self.arch).split()
                    distname = section

                ### Add a distribution for each arch
                for arch in archlist:
                    dist = Dist(distname, arch, self)
                    dist.arch = arch
                    dist.metadata = self.metadata.split()
                    dist.enabled = True
                    dist.promoteepoch = True
                    dist.systemid = None
                    for option in self.cfg.options(section):
                        if option in ('name', 'release', 'repo'):
                            setattr(dist, option, self.cfg.get(section, option))
                        elif option in ('arch', 'dist'):
                            pass
                        elif option in ('disabled',):
                            dist.enabled = self.cfg.get(section, option) in DISABLE
                        elif option in ('metadata',):
                            setattr(dist, option, self.cfg.get(section, option).split())
                        elif option in ('promoteepoch',):
                            dist.promoteepoch = self.cfg.get(section, option) not in DISABLE
                        elif option in ('systemid',):
                            dist.systemid = self.cfg.get(section, option)
                        elif option in ('sslcert',):
                            dist.sslcert = self.cfg.get(section, option)
                        elif option in ('sslkey',):
                            dist.sslkey = self.cfg.get(section, option)
                        elif option in ('sslca',):
                            dist.sslca = self.cfg.get(section, option)
                        else:
                            dist.repos.append(Repo(option, self.cfg.get(section, option), dist, self))

                    dist.repos.sort(reposort)
                    dist.rewrite()

                    self.alldists.append(dist)

                    if dist.enabled:
                        self.dists.append(dist)
                    else:
                        info(5, '%s: %s is disabled' % (dist.nick, dist.name))

        self.alldists.sort(distsort)
        self.dists.sort(distsort)

    def getoption(self, section, option, var):
        "Get an option from a section from configfile"
        try:
            var = self.cfg.get(section, option)
            info(3, 'Setting option %s in section [%s] to: %s' % (option, section, var))
        except ConfigParser.NoSectionError:
            error(5, 'Failed to find section [%s]' % section)
        except ConfigParser.NoOptionError:
            info(5, 'Setting option %s in section [%s] to: %s (default)' % (option, section, var))
        return var


class Dist(object):
    def __init__(self, dist, arch, config):
        self.arch = arch
        self.dist = dist
        self.enabled = False
        self.nick = dist + '-' + arch
        if arch == 'none':
            self.nick = dist
        self.name = dist
        self.metadata = []
        self.dir = path_join(config.wwwdir, self.nick)
        self.promoteepoch = None
        self.release = None
        self.repos = []
        self.srcdir = config.srcdir
        self.systemid = None
        self.sslcert = None
        self.sslkey = None
        self.sslca = None


    def rewrite(self):
        "Rewrite (string) attributes to replace variables by other (string) attributes"
        varlist = VARIABLES
        varlist.update({
            'arch': self.arch,
            'nick': self.nick,
            'dist': self.dist,
            'release': self.release,
        })
        for key, value in vars(self).iteritems():
            if isinstance(value, types.StringType):
                setattr(self, key, substitute(value, varlist))
        for repo in self.repos:
            varlist['repo'] = repo.name
            repo.url = substitute(repo.url, varlist)

    def listrepos(self, names=None):
        if names:
            return [repo for repo in self.repos if repo.name in names]
        return self.repos

    def genmetadata(self):
        for repo in self.listrepos(OPTIONS.repos):
            if not repo.lock('generate'):
                continue

            self.linksync(repo, [repo.srcdir])

            repo.check()
            repo.createmd()

            ### After generation, write a sha1sum
            repo.writesha1()
            repo.unlock('generate')

    def linksync(self, repo, srcdirs=None):
        if not srcdirs:
            srcdirs = [repo.srcdir]
        destdir = repo.wwwdir
        srcfiles = listrpms(srcdirs, relative=destdir)
        # srcfiles = [ (basename, relpath), ... ]
        srcfiles.sort()
        # uniq basenames
        srcfiles = [f for i, f in enumerate(srcfiles)
                    if not i or f[0] != srcfiles[i - 1][0]]

        info(5, '%s: Symlink %s packages from %s to %s' % (repo.dist.nick, repo.name, srcdirs, destdir))
        mkdir(destdir)

        destfiles = listrpmlinks(destdir)
        # destfiles is a list of (link_target_base, link_target_dir) tuples
        destfiles.sort()

        def keyfunc(key):
            # compare the basenames
            return key[0]

        changed = False
        for srcfile, destfile in synciter(srcfiles, destfiles, key=keyfunc):
            if srcfile is None:
                # delete the link
                base, _ = destfile
                linkname = path_join(destdir, base)
                info(5, 'Remove link: %s' % (linkname,))
                if not OPTIONS.dryrun:
                    os.unlink(linkname)
                    changed = True
            elif destfile is None:
                base, srcdir = srcfile
                # create a new link
                linkname = path_join(destdir, base)
                target = path_join(srcdir, base)
                info(5, 'New link: %s -> %s' % (linkname, target))
                if not OPTIONS.dryrun:
                    os.symlink(target, linkname)
                    changed = True
            else:
                # same bases
                base, srcdir = srcfile
                _, curtarget = destfile
                target = path_join(srcdir, base)
                if target != curtarget:
                    info(5, 'Changed link %s: current: %s, should be: %s' % (base, curtarget, target))
                    linkname = path_join(destdir, base)
                    if not OPTIONS.dryrun:
                        os.unlink(linkname)
                        os.symlink(target, linkname)
                        changed = True

        if changed:
            repo.changed = True


class Repo(object):
    def __init__(self, name, url, dist, config):
        self.name = name
        self.url = url
        self.dist = dist
        self.srcdir = path_join(config.srcdir, dist.nick, self.name)
        self.wwwdir = path_join(dist.dir, 'RPMS.' + self.name)

        self.changed = False

        self.oldlist = set()
        self.newlist = set()

    def __repr__(self):
        return self.name

    def mirror(self):
        "Check URL and pass on to mirror-functions."
        global EXITCODE # pylint: disable=global-statement

        ### Make a snapshot of the directory
        self.oldlist = self.rpmlist()
        self.newlist = self.oldlist

        for url in self.url.split():
            try:
                info(2, '%s: Mirror packages from %s to %s' % (self.dist.nick, url, self.srcdir))
                scheme = urlparse.urlparse(url)[0]
                if scheme not in OPTIONS.types:
                    info(4, 'Ignoring mirror action for type %s' % scheme)
                    continue
                if scheme in ('rsync', ):
                    mirrorrsync(url, self.srcdir)
                elif scheme in ('ftp', 'fish', 'http', 'https', 'sftp'):
                    mirrorlftp(url, self.srcdir, self.dist)
                elif scheme in ('reposync', 'reposyncs', 'reposyncf'):
                    mirrorreposync(url, self.srcdir, '%s-%s' % (self.dist.nick, self.name), self.dist)
                else:
                    error(2, 'Scheme %s:// not implemented yet (in %s)' % (scheme, url))
            except MrepoMirrorException as instance:
                error(0, 'Mirroring failed for %s with message:\n  %s' % (url, instance.value))
                EXITCODE = 2
        if not self.url:
            ### Create directory in case no URL is given
            mkdir(self.srcdir)

        ### Make a snapshot of the directory
        self.newlist = self.rpmlist()

    def rpmlist(self):
        "Capture a list of packages in the repository"
        filelist = set()

        def addfile((filelist, ), path, files):
            for filename in files:
                if path_exists(path_join(path, filename)) and filename.endswith('.rpm'):
                    size = os.stat(path_join(path, filename)).st_size
                    filelist.add((filename, size))

        os.path.walk(self.srcdir, addfile, (filelist,))
        return filelist

    def check(self):
        "Return what repositories require an update and write .newsha1sum"
        if not path_is_dir(self.wwwdir):
            return
        sha1file = path_join(self.wwwdir, '.sha1sum')
        remove(sha1file + '.tmp')
        cursha1 = sha1dir(self.wwwdir)
        if OPTIONS.force:
            pass
        elif os.path.isfile(sha1file):
            oldsha1 = open(sha1file).read()
            if cursha1 != oldsha1:
                info(2, '%s: Repository %s has new packages.' % (self.dist.nick, self.name))
            else:
                info(5, '%s: Repository %s has not changed. Skipping.' % (self.dist.nick, self.name))
                return
        else:
            info(5, '%s: New repository %s detected.' % (self.dist.nick, self.name))
        writesha1(sha1file + '.tmp', cursha1)
        self.changed = True

    def writesha1(self):
        "Verify .newsha1sum and write a .sha1sum file per repository"
        sha1file = path_join(self.wwwdir, '.sha1sum')
        if os.path.isfile(sha1file + '.tmp'):
            cursha1 = sha1dir(self.wwwdir)
            tmpsha1 = open(sha1file + '.tmp').read()
            remove(sha1file + '.tmp')
            if cursha1 == tmpsha1:
                writesha1(sha1file, cursha1)
            else:
                info(5, '%s: Checksum is different. expect: %s, got: %s' % (
                    self.dist.nick,
                    cursha1,
                    tmpsha1,
                ))
                info(1, '%s: Directory changed during generating %s repo, please generate again.' % (
                    self.dist.nick,
                    self.name,
                ))

    def lock(self, action):
        if OPTIONS.dryrun:
            return True
        lockfile = path_join(CONFIG.lockdir, self.dist.nick, action + '-' + self.name + '.lock')
        mkdir(os.path.dirname(lockfile))
        try:
            file_object = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o0600)
            info(6, '%s: Setting lock %s' % (self.dist.nick, lockfile))
            os.write(file_object, '%d' % os.getpid())
            os.close(file_object)
            return True
        except OSError:
            if path_exists(lockfile):
                pid = open(lockfile).read()
                if path_exists('/proc/%s' % pid):
                    error(0, '%s: Found existing lock %s owned by pid %s' % (self.dist.nick, lockfile, pid))
                else:
                    info(6, '%s: Removing stale lock %s' % (self.dist.nick, lockfile))
                    os.unlink(lockfile)
                    self.lock(action)
                    return True
            else:
                error(0, '%s: Lockfile %s does not exist. Cannot lock. Parallel universe ?' % (
                    self.dist.nick,
                    lockfile,
                ))
        return False

    def unlock(self, action):
        if OPTIONS.dryrun:
            return
        lockfile = path_join(CONFIG.lockdir, self.dist.nick, action + '-' + self.name + '.lock')
        info(6, '%s: Removing lock %s' % (self.dist.nick, lockfile))
        if path_exists(lockfile):
            pid = open(lockfile).read()
            if pid == '%s' % os.getpid():
                os.unlink(lockfile)
            else:
                error(0, '%s: Existing lock %s found owned by another process with pid %s. This should NOT happen.' % (
                    self.dist.nick,
                    lockfile,
                    pid,
                ))
        else:
            error(0, '%s: Lockfile %s does not exist. Cannot unlock. Something fishy here ?' % (
                self.dist.nick,
                lockfile,
            ))

    def createmd(self):
        global EXITCODE # pylint: disable=global-statement
        metadata = ('createrepo', 'repomd')

        if not self.changed and not OPTIONS.force:
            return

        try:
            ### Generate repository metadata
            for metadata in self.dist.metadata:
                if metadata in ('createrepo', 'repomd'):
                    self.repomd()

        except MrepoGenerateException as instance:
            error(0, 'Generating repo failed for %s with message:\n  %s' % (self.name, instance.value))
            EXITCODE = 2

    def repomd(self):
        "Create a repomd repository"
        if not CONFIG.cmd['createrepo']:
            raise MrepoGenerateException('Command createrepo is not found. Skipping.')

        opts = ' ' + CONFIG.createrepooptions
        if OPTIONS.force:
            opts = ' --pretty' + opts
        if OPTIONS.verbose <= 2:
            opts = ' --quiet' + opts
        elif OPTIONS.verbose >= 4:
            opts = ' -v' + opts
        if not self.dist.promoteepoch:
            opts = opts + ' -n'
        if path_is_dir(self.wwwdir):
            repoopts = opts
            if CONFIG.cachedir:
                cachedir = path_join(CONFIG.cachedir, self.dist.nick, self.name)
                mkdir(cachedir)
                repoopts = repoopts + ' --cachedir "%s"' % cachedir
            if path_is_dir(path_join(self.wwwdir, '.olddata')):
                remove(path_join(self.wwwdir, '.olddata'))
            groupfile = path_join(CONFIG.srcdir, self.dist.nick, self.name + '-comps.xml')
            if os.path.isfile(groupfile):
                symlink(groupfile, path_join(self.wwwdir, 'comps.xml'))
                repoopts = repoopts + ' --groupfile "%s"' % groupfile
            info(2, '%s: Create repomd repository for %s' % (self.dist.nick, self.name))
            ret = run('%s %s %s' % (CONFIG.cmd['createrepo'], repoopts, self.wwwdir))
            if ret:
                raise MrepoGenerateException('%s failed with return code: %s' % (CONFIG.cmd['createrepo'], ret))


class MrepoMirrorException(Exception):
    def __init__(self, value):
        self.value = value
        Exception.__init__(self)

    def __str__(self):
        return repr(self.value)


class MrepoGenerateException(Exception):
    def __init__(self, value):
        self.value = value
        Exception.__init__(self)

    def __str__(self):
        return repr(self.value)


def sha1dir(directory):
    "Return sha1sum of a directory"
    files = glob.glob(directory + '/*.rpm')
    files.sort()
    output = ''
    for filename in files:
        output = output + os.path.basename(filename) + ' ' + str(os.stat(filename).st_size) + '\n'
    return sha1hash(output).hexdigest()


def writesha1(filename, sha1sum=None):
    "Write out sha1sum"
    repodir = os.path.dirname(filename)
    if not sha1sum:
        sha1sum = sha1dir(repodir)
    if not OPTIONS.dryrun:
        open(filename, 'w').write(sha1sum)


def error(level, text):
    "Output error message"
    if level <= OPTIONS.verbose:
        sys.stderr.write('mrepo: %s\n' % text)


def info(level, text):
    "Output info message"
    if level <= OPTIONS.verbose:
        sys.stdout.write('%s\n' % text)


def die(ret, text):
    "Print error and exit with errorcode"
    error(0, text)
    sys.exit(ret)


def run(text, dryrun=False):
    "Run command, accept user input, and print output when needed."
    text = 'exec ' + text
    if OPTIONS.verbose <= 2:
        text = text + ' >/dev/null'
    if not OPTIONS.dryrun or dryrun:
        info(5, 'Execute: %s' % text)
        return os.system(text)
    info(1, 'Not execute: %s' % text)
    return 0


def readfile(filename, size=0):
    "Return content of a file"
    if not os.path.isfile(filename):
        return None
    if size:
        return open(filename, 'r').read(size)
    return open(filename, 'r').read()


def writefile(filename, text):
    if OPTIONS.dryrun:
        return
    file_object = open(filename, 'w')
    file_object.write(text)
    file_object.close()


def substitute(string, variables, recursion=0):
    "Substitute variables from a string"
    if recursion > 10:
        raise RuntimeError, "variable substitution loop"

    def _substrepl(matchobj):
        value = variables.get(matchobj.group(1))
        if value is not None:
            return substitute(value, variables, recursion + 1)
        return matchobj.group(0)

    string = _SUBST_SUB(_substrepl, string)
    return string


def distsort(a, b): # pylint: disable=invalid-name
    return cmp(a.nick, b.nick)


def reposort(a, b): # pylint: disable=invalid-name
    return cmp(a.name, b.name)


def vercmp(a, b): # pylint: disable=invalid-name
    a = a.split('.')
    b = b.split('.')
    minlen = min(len(a), len(b))
    for i in range(1, minlen):
        if cmp(a[i], b[i]) < 0:
            return -1
        elif cmp(a[i], b[i]) > 0:
            return 1
    return cmp(len(a), len(b))


def symlinkglob(text, *targets):
    "Symlink files to multiple targets"
    for filename in glob.glob(text):
        for target in targets:
            mkdir(target)
            symlink(filename, target)


def abspath(path, reference):
    "Make absolute path from reference"
    return os.path.normpath(path_join(path, reference))


def relpath(path, reference):
    """Make relative path from reference
       if reference is a directory, it must end with a /"""
    common = os.path.commonprefix([path, reference])
    common = common[0:common.rfind('/') + 1]
    (uncommon, _) = os.path.split(reference.replace(common, '', 1))
    if uncommon:
        newpath = []
        for _ in uncommon.split('/'):
            newpath.append('..')
        newpath.append(path.replace(common, '', 1))
        return '/'.join(newpath)
    return path


def symlink(src, dst):
    "Create a symbolic link, force if dst exists"
    if OPTIONS.dryrun:
        return
    elif os.path.islink(dst):
        if os.path.samefile(src, abspath(os.readlink(dst), src)):
            return
        os.unlink(dst)
    elif path_is_dir(dst):
        if path_is_dir(src):
            if os.path.samefile(src, dst):
                return
        else:
            dst = path_join(dst, os.path.basename(src))
            symlink(src, dst)
            return
    elif os.path.isfile(dst):
        if os.path.samefile(src, dst):
            return
        os.rename(dst, dst + '.mrepobak')

    src = relpath(src, dst)

    if not path_is_dir(os.path.dirname(dst)):
        mkdir(os.path.dirname(dst))
    os.symlink(src, dst)


def copy(src, dst):
    "Copy a file, force if dst exists"
    if OPTIONS.dryrun:
        return
    if path_is_dir(dst):
        dst = path_join(dst, os.path.basename(src))
    if os.path.islink(dst) or os.path.isfile(dst):
        os.unlink(dst)
    mkdir(os.path.dirname(dst))
    if not path_exists(dst):
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif path_is_dir(src):
            shutil.copytree(src, dst)


def remove(filename):
    "Remove files or directories"
    if isinstance(filename, types.StringType):
        if OPTIONS.dryrun:
            return
        if os.path.islink(filename):
            os.unlink(filename)
        elif path_is_dir(filename):
            try:
                os.rmdir(filename)
            except OSError:
                os.path.walk(filename, removedir, ())
                os.rmdir(filename)
        elif os.path.isfile(filename) or os.path.islink(filename):
            os.unlink(filename)
    else:
        for name in filename:
            remove(name)


def removedir(_, directory, files):
    for filename in files:
        remove(path_join(directory, filename))


def mkdir(path):
    "Create a directory, and parents if needed"
    if OPTIONS.dryrun:
        return
    if os.path.islink(path):
        os.unlink(path)
    if not path_exists(path):
        os.makedirs(path)


def mirrorrsync(url, path):
    "Mirror everything from an rsync:// URL"
    if not CONFIG.cmd['rsync']:
        error(1, 'rsync was not found. rsync support is therefore disabled.')
        return

    # Ensure both source and destination paths end with a trailing slash
    url = url.rstrip('/') + '/'
    path = path_join(path, '')

    mkdir(path)

    opts = CONFIG.rsyncoptions
    if OPTIONS.verbose <= 2:
        opts = opts + ' -q'
    elif OPTIONS.verbose == 3:
        opts = opts + ' -v'
    elif OPTIONS.verbose == 4:
        opts = opts + ' -v --progress'
    elif OPTIONS.verbose == 5:
        opts = opts + ' -vv --progress'
    elif OPTIONS.verbose >= 6:
        opts = opts + ' -vvv --progress'
    if OPTIONS.dryrun:
        opts = opts + ' --dry-run'
    if CONFIG.rsynctimeout:
        opts = opts + ' --timeout=%s' % CONFIG.rsynctimeout
    if CONFIG.rsynccleanup:
        opts = opts + ' --delete-after --delete-excluded'
    if CONFIG.rsyncbwlimit:
        opts = opts + ' --bwlimit=%s' % CONFIG.rsyncbwlimit
    if CONFIG.rsyncexclheaders:
        opts = opts + ' --exclude=\"/headers/\"'
    if CONFIG.rsyncexclrepodata:
        opts = opts + ' --exclude=\"/repodata/\"'
    if CONFIG.rsyncexclsrpm:
        opts = opts + ' --exclude=\"*.src.rpm\" --exclude=\"/SRPMS/\"'
    if CONFIG.rsyncexcldebug:
        opts = opts + ' --exclude=\"*-debuginfo-*.rpm\" --exclude=\"/debug/\"'
    opts = opts + ' --include=\"*.rpm\"'
    if CONFIG.rsyncexclsrpm or CONFIG.rsyncexcldebug:
        opts = opts + ' --exclude=\"*.*\"'

    ret = run('%s %s %s %s' % (CONFIG.cmd['rsync'], opts, url, path), dryrun=True)
    if ret:
        raise MrepoMirrorException('Failed with return code: %s' % ret)


def mirrorlftp(url, path, dist):
    "Mirror everything from a http://, ftp://, sftp://, fish:// URL"
    if not CONFIG.cmd['lftp']:
        error(1, 'lftp was not found. fish, ftp, http and sftp support (using lftp) is therefore disabled.')
        return
    mkdir(path)

    cmds = CONFIG.lftpcommands + ';'

    if dist.sslcert:
        cmds = cmds + ' set ssl:cert-file ' + dist.sslcert + ';'
    if dist.sslkey:
        cmds = cmds + ' set ssl:key-file ' + dist.sslkey + ';'
    if dist.sslca:
        cmds = cmds + ' set ssl:ca-file ' + dist.sslca + ' ;'

    if CONFIG.lftptimeout:
        cmds = cmds + ' set net:timeout %s;' % CONFIG.lftptimeout
    if CONFIG.lftpbwlimit:
        cmds = cmds + ' set net:limit-total-rate %s:0;' % CONFIG.lftpbwlimit

    opts = CONFIG.lftpoptions
    if OPTIONS.verbose >= 6:
        opts = opts + ' -d'

    mirroropts = CONFIG.lftpmirroroptions
    if OPTIONS.verbose >= 3:
        mirroropts = mirroropts + ' -v' * (OPTIONS.verbose - 2)
    if OPTIONS.dryrun:
        mirroropts = mirroropts + ' --dry-run'
    if CONFIG.lftpcleanup:
        mirroropts = mirroropts + ' -e'
    mirroropts = mirroropts + ' -I *.rpm -X \"/headers/\" -X \"/repodata/\"'
    if CONFIG.lftpexclsrpm:
        mirroropts = mirroropts + ' -X \"*.src.rpm\" -X \"/SRPMS/\"'
    if CONFIG.lftpexcldebug:
        mirroropts = mirroropts + ' -X \"*-debuginfo-*.rpm\" -X \"/debug/\"'

    ret = run('%s %s -c \'%s mirror %s %s %s\'' % (CONFIG.cmd['lftp'], opts, cmds, mirroropts, url, path), dryrun=True)
    if ret:
        raise MrepoMirrorException('Failed with return code: %s' % ret)


def mirrorreposync(url, path, reponame, dist):
    "Mirror everything from a reposync:// URL"
    if not CONFIG.cmd['reposync']:
        error(1, 'reposync was not found. reposync support is therefore disabled.')
        return
    mkdir(path)

    url = url.replace('reposyncs://', 'https://')
    url = url.replace('reposync://', 'http://')
    url = url.replace('reposyncf://', 'ftp://')

    opts = CONFIG.reposyncoptions
    if OPTIONS.verbose < 3:
        opts = opts + ' -q'
    if OPTIONS.dryrun:
        opts = opts + ' --urls'
    if CONFIG.reposynccleanup:
        opts = opts + ' --delete'
    if CONFIG.reposyncnewestonly:
        opts = opts + ' --newest-only'
    if CONFIG.reposyncnorepopath:
        opts = opts + ' --norepopath'

    # store a temporary YUM config to use with reposync
    reposync_conf_contents = "[%s]\n" % reponame
    reposync_conf_contents += "name=%s\n" % reponame
    reposync_conf_contents += "baseurl=%s\n" % url
    reposync_conf_contents += "enabled=1\n"
    if dist.sslca:
        reposync_conf_contents += "sslcacert=%s\n" % dist.sslca
    if dist.sslcert:
        reposync_conf_contents += "sslclientcert=%s\n" % dist.sslcert
    if dist.sslkey:
        reposync_conf_contents += "sslclientkey=%s\n" % dist.sslkey
    if CONFIG.reposynctimeout:
        reposync_conf_contents += "timeout=%s\n" % CONFIG.reposynctimeout
    if CONFIG.reposyncminrate:
        reposync_conf_contents += "minrate=%s\n" % CONFIG.reposyncminrate

    # Only mirror packages exactly matching arch
    reposync_conf_contents += "includepkgs=*.%s\n" % dist.arch

    (file_object, reposync_conf_file) = tempfile.mkstemp(text=True)
    handle = os.fdopen(file_object, 'w')
    handle.writelines(reposync_conf_contents)
    handle.close()

    ret = run("%s %s --metadata-path %s/reposync --config '%s' --repoid %s --download-path '%s'" % (
        CONFIG.cmd['reposync'],
        opts,
        CONFIG.cachedir,
        reposync_conf_file,
        reponame,
        path,
    ))

    # remove the temporary config
    os.remove(reposync_conf_file)

    if ret:
        raise MrepoMirrorException('Failed with return code: %s' % ret)


def which(cmd):
    "Find executables in PATH environment"
    for path in os.environ.get('PATH', '$PATH').split(':'):
        if os.path.isfile(path_join(path, cmd)):
            info(5, 'Found command %s in path %s' % (cmd, path))
            return path_join(path, cmd)
    return ''


def mail(subject, msg):
    info(2, 'Sending mail to: %s' % CONFIG.mailto)
    try:
        smtp = smtplib.SMTP(CONFIG.smtpserver)
        msg = 'Subject: [mrepo] %s\nX-Mailer: mrepo %s\n\n%s' % (subject, VERSION, msg)
        for email in CONFIG.mailto.split():
            smtp.sendmail(CONFIG.mailfrom, email, 'To: %s\n%s' % (email, msg))
        smtp.quit()
    except smtplib.SMTPException:
        info(1, 'Sending mail via %s failed.' % CONFIG.smtpserver)


def readconfig():
    config = Config()
    if config.confdir and path_is_dir(config.confdir):
        files = glob.glob(path_join(config.confdir, '*.conf'))
        files.sort()
        for configfile in files:
            config.read(configfile)
            config.update()
    return config


def _next_none(iterator):
    try:
        return iterator.next()
    except StopIteration:
        return None


def synciter(a, b, key=None, keya=None, keyb=None): # pylint: disable=invalid-name
    """returns an iterator that compares two ordered iterables a and b.
    If keya or keyb are specified, they are called with elements of the corresponding
    iterable. They should return a value that is used to compare two elements.
    If keya or keyb are not specified, they default to key or to the element itself,
    if key is None."""

    if key is None:
        key = lambda x: x
    if keya is None:
        keya = key
    if keyb is None:
        keyb = key
    a = iter(a)
    b = iter(b)
    aelem = _next_none(a)
    belem = _next_none(b)
    while not ((aelem is None) or (belem is None)):
        akey = keya(aelem)
        bkey = keyb(belem)
        if akey == bkey:
            yield aelem, belem
            aelem = _next_none(a)
            belem = _next_none(b)
        elif akey > bkey:
            # belem missing in a
            yield None, belem
            belem = _next_none(b)
        elif bkey > akey:
            # aelem missing in b
            yield aelem, None
            aelem = _next_none(a)
    # rest
    while aelem is not None:
        akey = key(aelem)
        yield aelem, None
        aelem = _next_none(a)
    while belem is not None:
        bkey = key(belem)
        yield None, belem
        belem = _next_none(b)


def listrpms(directories, relative=''):
    """return a list of rpms in the given directories as a list of (name, path) tuples
    if relative is specified, return the paths relative to this directory"""
    if not isinstance(directories, (list, tuple)):
        directories = (directories,)
    if relative and not relative.endswith('/'):
        relative += '/'

    def processdir(rpms, path, filenames):
        final_path = path
        if relative:
            final_path = relpath(path, relative)
        for filename in filenames:
            filepath = path_join(path, filename)
            if filename.endswith('.rpm') and path_exists(filepath) and not path_is_dir(filepath):
                rpms.append((filename, final_path))

    rpms = []
    for directory in directories:
        if not directory.startswith('/'):
            directory = path_join(relative, directory)
        os.path.walk(directory, processdir, rpms)
    rpms.sort()
    return rpms


def listrpmlinks(directory):
    islink = os.path.islink
    readlink = os.readlink
    links = []
    for filename in os.listdir(directory):
        path = path_join(directory, filename)
        if islink(path) and filename.endswith('.rpm'):
            links.append((filename, readlink(path)))
    return links


def main():
    ### Check availability of commands
    for cmd in CONFIG.cmd:
        if not CONFIG.cmd[cmd]:
            continue
        cmdlist = CONFIG.cmd[cmd].split()
        if not os.path.isfile(cmdlist[0]):
            cmdlist[0] = which(cmdlist[0])
        if cmdlist[0] and not os.path.isfile(cmdlist[0]):
            error(4, '%s command not found as %s, support disabled' % (cmd, cmdlist[0]))
            CONFIG.cmd[cmd] = ''
        else:
            CONFIG.cmd[cmd] = ' '.join(cmdlist)
    if not CONFIG.cmd['createrepo']:
        error(1, 'No tools found to generate repository metadata. Please install createrepo.')

    ### Set proxy-related environment variables
    if CONFIG.no_proxy:
        os.environ['no_proxy'] = CONFIG.no_proxy
    if CONFIG.ftp_proxy:
        os.environ['ftp_proxy'] = CONFIG.ftp_proxy
    if CONFIG.http_proxy:
        os.environ['http_proxy'] = CONFIG.http_proxy
    if CONFIG.https_proxy:
        os.environ['https_proxy'] = CONFIG.https_proxy
    if CONFIG.rsync_proxy:
        os.environ['RSYNC_PROXY'] = CONFIG.rsync_proxy

    ### Select list of distributions in order of appearance
    if not OPTIONS.dists:
        dists = CONFIG.dists
    else:
        dists = []
        for name in OPTIONS.dists:
            append = False
            for dist in CONFIG.alldists:
                if name == dist.nick or name == dist.dist:
                    dists.append(dist)
                    append = True
            if not append:
                error(1, 'Distribution %s not defined' % name)

    sumnew = 0
    sumremoved = 0
    msg = 'The following changes to mrepo\'s repositories on %s have been made:' % os.uname()[1]

    ### Mounting and mirroring available distributions/repositories
    for dist in dists:
        if OPTIONS.update:
            msg = msg + '\n\nDist: %s (%s)' % (dist.name, dist.nick)
            info(1, '%s: Updating %s' % (dist.nick, dist.name))

            distnew = 0
            distremoved = 0

            ### Downloading things
            for repo in dist.listrepos(OPTIONS.repos):
                if not repo.lock('update'):
                    continue
                if repo in dist.listrepos():
                    repo.mirror()
                else:
                    info(2, '%s: Repository %s does not exist' % (dist.nick, repo.name))
                    repo.unlock('update')
                    continue

                repo.unlock('update')

                ### files whose size has changed are in new and removed!
                new = repo.newlist.difference(repo.oldlist)
                removed = repo.oldlist.difference(repo.newlist)

                if new or removed:
                    msg = msg + '\n\n\tRepo: %s' % repo.name
                    info(2, '%s: Repository %s changed (new: %d, removed: %d)' % (
                        dist.nick,
                        repo.name,
                        len(new),
                        len(removed),
                    ))
                    file_object = open(CONFIG.logfile, 'a+')
                    date = time.strftime("%b %d %H:%M:%S", time.gmtime())

                    def sortedlist(pkgs):
                        result = list(pkgs)
                        result.sort()
                        return result

                    def formatlist(pkglist):
                        return '\n\t' + '\n\t'.join([elem[0] for elem in pkglist])

                    if new:
                        pkglist = sortedlist(new)
                        info(4, '%s: New packages: %s' % (dist.nick, formatlist(pkglist)))
                        distnew += len(pkglist)
                        for element in pkglist:
                            file_object.write('%s %s/%s Added %s (%d kiB)\n' % (
                                date,
                                dist.nick,
                                repo.name,
                                element[0],
                                element[1] / 1024,
                            ))
                            msg = msg + '\n\t\t+ %s (%d kiB)' % (element[0], element[1] / 1024)

                    if removed:
                        pkglist = sortedlist(removed)
                        info(4, '%s: Removed packages: %s' % (dist.nick, formatlist(pkglist)))
                        distremoved += len(pkglist)
                        for element in pkglist:
                            file_object.write('%s %s/%s Removed %s (%d kiB)\n' % (
                                date,
                                dist.nick,
                                repo.name,
                                element[0],
                                element[1] / 1024,
                            ))
                            msg = msg + '\n\t\t- %s (%d kiB)' % (element[0], element[1] / 1024)

                    file_object.close()
                    repo.changed = True

            if distnew or distremoved:
                msg = msg + '\n'
                info(1, '%s: Distribution updated (new: %d, removed: %d)' % (dist.nick, distnew, distremoved))
                sumnew = sumnew + distnew
                sumremoved = sumremoved + distremoved

    if sumnew or sumremoved:
        subject = 'changes to %s (new: %d, removed: %d)' % (os.uname()[1], sumnew, sumremoved)
        mail(subject, msg)

    if not OPTIONS.generate:
        sys.exit(0)


    ### Generating metadata for available distributions/repositories
    for dist in dists:
        info(1, '%s: Generating %s meta-data' % (dist.nick, dist.name))

        dist.genmetadata()


### Unbuffered sys.stdout
sys.stdout = os.fdopen(1, 'w', 0)
sys.stderr = os.fdopen(2, 'w', 0)

### Main entrance
if __name__ == '__main__':
    OPTIONS = Options(sys.argv[1:])
    CONFIG = readconfig()
    try:
        main()
    except KeyboardInterrupt:
        die(6, 'Exiting on user request')
    sys.exit(EXITCODE)

# vim:ts=4:sw=4:et
