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
import re
import tempfile

from hashlib import sha1 as sha1hash

import shutil
import sys
import time
import types
import urlparse
import urllib

__version__ = "$Revision$"
# $Source$

VERSION = "0.8.9"

archs = {
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

variables = {}

disable = ('no', 'off', 'false', '0')

for scheme in ('reposync', 'reposyncs', 'reposyncf'):
    urlparse.uses_netloc.insert(0, scheme)
    urlparse.uses_query.insert(0, scheme)


class Options:
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
            opts, args = getopt.getopt(args, 'c:d:fghnqr:t:uvx',
                ('config=', 'dist=', 'dry-run', 'force', 'generate', 'help', 'quiet', 'repo=',
                 'type=', 'update', 'verbose', 'version', 'extras'))
        except getopt.error, exc:
            print 'mrepo: %s, try mrepo -h for a list of all the options' % str(exc)
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


class Config:
    def __init__(self):
        self.read(op.configfile)

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

        self.quiet = self.getoption('main', 'quiet', 'no') not in disable
        if op.verbose == 1 and self.quiet:
            op.verbose = 0

        self.no_proxy = self.getoption('main', 'no_proxy', None)
        self.ftp_proxy = self.getoption('main', 'ftp_proxy', None)
        self.http_proxy = self.getoption('main', 'http_proxy', None)
        self.https_proxy = self.getoption('main', 'https_proxy', None)
        self.RSYNC_PROXY = self.getoption('main', 'RSYNC_PROXY', None)

        self.cmd = {}
        self.cmd['createrepo'] = self.getoption('main', 'createrepocmd', '/usr/bin/createrepo')
        self.cmd['lftp'] = self.getoption('main', 'lftpcmd', '/usr/bin/lftp')
        self.cmd['reposync'] = self.getoption('main', 'reposynccmd', '/usr/bin/reposync')
        self.cmd['rsync'] = self.getoption('main', 'rsynccmd', '/usr/bin/rsync')

        self.createrepooptions = self.getoption('main', 'createrepo-options', '--pretty --database --update')

        self.lftpbwlimit = self.getoption('main', 'lftp-bandwidth-limit', None)
        self.lftpcleanup = self.getoption('main', 'lftp-cleanup', 'yes') not in disable
        self.lftpexcldebug = self.getoption('main', 'lftp-exclude-debug', 'yes') not in disable
        self.lftpexclsrpm = self.getoption('main', 'lftp-exclude-srpm', 'yes') not in disable
        self.lftpoptions = self.getoption('main', 'lftp-options', '')
        self.lftpcommands = self.getoption('main', 'lftp-commands', '')
        self.lftpmirroroptions = self.getoption('main', 'lftp-mirror-options', '-c')
        self.lftptimeout = self.getoption('main', 'lftp-timeout', None)

        self.reposyncoptions = self.getoption('main', 'reposync-options', '')
        self.reposynccleanup = self.getoption('main', 'reposync-cleanup', 'yes') not in disable
        self.reposyncnewestonly = self.getoption('main', 'reposync-newest-only', 'no') not in disable
        self.reposyncexcldebug = self.getoption('main','reposync-exclude-debug', 'yes') not in disable
        self.reposyncnorepopath = self.getoption('main','reposync-no-repopath', 'yes') not in disable
        self.reposynctimeout = self.getoption('main','reposync-timeout', '90')
        self.reposyncminrate = self.getoption('main','reposync-minrate', '250')

        self.rsyncbwlimit = self.getoption('main', 'rsync-bandwidth-limit', None)
        self.rsynccleanup = self.getoption('main', 'rsync-cleanup', 'yes') not in disable
        self.rsyncexclheaders = self.getoption('main', 'rsync-exclude-headers', 'yes') not in disable
        self.rsyncexclrepodata = self.getoption('main', 'rsync-exclude-repodata', 'yes') not in disable
        self.rsyncexcldebug = self.getoption('main', 'rsync-exclude-debug', 'yes') not in disable
        self.rsyncexclsrpm = self.getoption('main', 'rsync-exclude-srpm', 'yes') not in disable
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
            except ConfigParser.MissingSectionHeaderError:
                die(6, 'Error accessing URL: %s' % configfile)
        else:
            if os.access(configfile, os.R_OK):
                try:
                    self.cfg.read(configfile)
                except:
                    die(7, 'Syntax error reading file: %s' % configfile)
            else:
                die(6, 'Error accessing file: %s' % configfile)

    def update(self):
        for section in ('variables', 'vars', 'DEFAULT'):
            if section in self.cfg.sections():
                for option in self.cfg.options(section):
                    variables[option] = self.cfg.get(section, option)

        for section in self.cfg.sections():
            if section in ('main', 'repos', 'variables', 'vars', 'DEFAULT'):
                continue
            else:
                ### Check if section has appended arch
                for arch in archs.keys():
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
                            dist.enabled = self.cfg.get(section, option) in disable
                        elif option in ('metadata',):
                            setattr(dist, option, self.cfg.get(section, option).split())
                        elif option in ('promoteepoch',):
                            dist.promoteepoch = self.cfg.get(section, option) not in disable
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
        except ConfigParser.NoSectionError, e:
            error(5, 'Failed to find section [%s]' % section)
        except ConfigParser.NoOptionError, e:
            info(5, 'Setting option %s in section [%s] to: %s (default)' % (option, section, var))
        return var


class Dist:
    def __init__(self, dist, arch, cf):
        self.arch = arch
        self.dist = dist
        self.nick = dist + '-' + arch
        if arch == 'none':
            self.nick = dist
        self.name = dist
        self.dir = os.path.join(cf.wwwdir, self.nick)
        self.release = None
        self.repos = []
        self.srcdir = cf.srcdir
        self.disabled = False
        self.sslcert = None
        self.sslkey = None
        self.sslca = None

    def rewrite(self):
        "Rewrite (string) attributes to replace variables by other (string) attributes"
        varlist = variables
        varlist.update({'arch': self.arch,
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
        else:
            return self.repos

    def genmetadata(self):
        pathjoin = os.path.join
        for repo in self.listrepos(op.repos):
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

        pathjoin = os.path.join

        def keyfunc(x):
            # compare the basenames
            return x[0]

        changed = False
        for srcfile, destfile in synciter(srcfiles, destfiles, key=keyfunc):
            if srcfile is None:
                # delete the link
                base, targetdir = destfile
                linkname = pathjoin(destdir, base)
                info(5, 'Remove link: %s' % (linkname,))
                if not op.dryrun:
                    os.unlink(linkname)
                    changed = True
            elif destfile is None:
                base, srcdir = srcfile
                # create a new link
                linkname = pathjoin(destdir, base)
                target = pathjoin(srcdir, base)
                info(5, 'New link: %s -> %s' % (linkname, target))
                if not op.dryrun:
                    os.symlink(target, linkname)
                    changed = True
            else:
                # same bases
                base, srcdir = srcfile
                base2, curtarget = destfile
                target = pathjoin(srcdir, base)
                if target != curtarget:
                    info(5, 'Changed link %s: current: %s, should be: %s' % (base, curtarget, target))
                    linkname = pathjoin(destdir, base)
                    if not op.dryrun:
                        os.unlink(linkname)
                        os.symlink(target, linkname)
                        changed = True

        if changed:
            repo.changed = True


class Repo:
    def __init__(self, name, url, dist, cf):
        self.name = name
        self.url = url
        self.dist = dist
        self.srcdir = os.path.join(cf.srcdir, dist.nick, self.name)
        self.wwwdir = os.path.join(dist.dir, 'RPMS.' + self.name)

        self.changed = False

        self.oldlist = set()
        self.newlist = set()

    def __repr__(self):
        return self.name

    def mirror(self):
        "Check URL and pass on to mirror-functions."
        global exitcode

        ### Make a snapshot of the directory
        self.oldlist = self.rpmlist()
        self.newlist = self.oldlist

        for url in self.url.split():
            try:
                info(2, '%s: Mirror packages from %s to %s' % (self.dist.nick, url, self.srcdir))
                s, l, p, q, f, o = urlparse.urlparse(url)
                if s not in op.types:
                    info(4, 'Ignoring mirror action for type %s' % s)
                    continue
                if s in ('rsync', ):
                    mirrorrsync(url, self.srcdir)
                elif s in ('ftp', 'fish', 'http', 'https', 'sftp'):
                    mirrorlftp(url, self.srcdir, self.dist)
                elif s in ('reposync', 'reposyncs', 'reposyncf'):
                    mirrorreposync(url, self.srcdir, '%s-%s' % (self.dist.nick, self.name), self.dist)
                else:
                    error(2, 'Scheme %s:// not implemented yet (in %s)' % (s, url))
            except mrepoMirrorException, e:
                error(0, 'Mirroring failed for %s with message:\n  %s' % (url, e.value))
                exitcode = 2
        if not self.url:
            ### Create directory in case no URL is given
            mkdir(self.srcdir)

        ### Make a snapshot of the directory
        self.newlist = self.rpmlist()

    def rpmlist(self):
        "Capture a list of packages in the repository"
        filelist = set()

        def addfile((filelist, ), path, files):
            for file in files:
                if os.path.exists(os.path.join(path, file)) and file.endswith('.rpm'):
                    size = os.stat(os.path.join(path, file)).st_size
                    filelist.add((file, size))

        os.path.walk(self.srcdir, addfile, (filelist,))
        return filelist

    def check(self):
        "Return what repositories require an update and write .newsha1sum"
        if not os.path.isdir(self.wwwdir):
            return
        sha1file = os.path.join(self.wwwdir, '.sha1sum')
        remove(sha1file + '.tmp')
        cursha1 = sha1dir(self.wwwdir)
        if op.force:
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
        sha1file = os.path.join(self.wwwdir, '.sha1sum')
        if os.path.isfile(sha1file + '.tmp'):
            cursha1 = sha1dir(self.wwwdir)
            tmpsha1 = open(sha1file + '.tmp').read()
            remove(sha1file + '.tmp')
            if cursha1 == tmpsha1:
                writesha1(sha1file, cursha1)
            else:
                info(5, '%s: Checksum is different. expect: %s, got: %s' % (self.dist.nick, cursha1, tmpsha1))
                info(1, '%s: Directory changed during generating %s repo, please generate again.' % (self.dist.nick, self.name))

    def lock(self, action):
        if op.dryrun:
            return True
        lockfile = os.path.join(cf.lockdir, self.dist.nick, action + '-' + self.name + '.lock')
        mkdir(os.path.dirname(lockfile))
        try:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0600)
            info(6, '%s: Setting lock %s' % (self.dist.nick, lockfile))
            os.write(fd, '%d' % os.getpid())
            os.close(fd)
            return True
        except:
            if os.path.exists(lockfile):
                pid = open(lockfile).read()
                if os.path.exists('/proc/%s' % pid):
                    error(0, '%s: Found existing lock %s owned by pid %s' % (self.dist.nick, lockfile, pid))
                else:
                    info(6, '%s: Removing stale lock %s' % (self.dist.nick, lockfile))
                    os.unlink(lockfile)
                    self.lock(action)
                    return True
            else:
                error(0, '%s: Lockfile %s does not exist. Cannot lock. Parallel universe ?' % (self.dist.nick, lockfile))
        return False

    def unlock(self, action):
        if op.dryrun:
            return True
        lockfile = os.path.join(cf.lockdir, self.dist.nick, action + '-' + self.name + '.lock')
        info(6, '%s: Removing lock %s' % (self.dist.nick, lockfile))
        if os.path.exists(lockfile):
            pid = open(lockfile).read()
            if pid == '%s' % os.getpid():
                os.unlink(lockfile)
            else:
                error(0, '%s: Existing lock %s found owned by another process with pid %s. This should NOT happen.' % (self.dist.nick, lockfile, pid))
        else:
            error(0, '%s: Lockfile %s does not exist. Cannot unlock. Something fishy here ?' % (self.dist.nick, lockfile))

    def createmd(self):
        metadata = ('createrepo', 'repomd')

        if not self.changed and not op.force:
            return

        try:
            ### Generate repository metadata
            for md in self.dist.metadata:
                if md in ('createrepo', 'repomd'):
                    self.repomd()

        except mrepoGenerateException, e:
            error(0, 'Generating repo failed for %s with message:\n  %s' % (self.name, e.value))
            exitcode = 2

    def repomd(self):
        "Create a repomd repository"
        if not cf.cmd['createrepo']:
            raise mrepoGenerateException('Command createrepo is not found. Skipping.')

        groupfilename = 'comps.xml'

        opts = ' ' + cf.createrepooptions
        if op.force:
            opts = ' --pretty' + opts
        if op.verbose <= 2:
            opts = ' --quiet' + opts
        elif op.verbose >= 4:
            opts = ' -v' + opts
        if not self.dist.promoteepoch:
            opts = opts + ' -n'
        if os.path.isdir(self.wwwdir):
            repoopts = opts
            if cf.cachedir:
                cachedir = os.path.join(cf.cachedir, self.dist.nick, self.name)
                mkdir(cachedir)
                repoopts = repoopts + ' --cachedir "%s"' % cachedir
            if os.path.isdir(os.path.join(self.wwwdir, '.olddata')):
                remove(os.path.join(self.wwwdir, '.olddata'))
            groupfile = os.path.join(cf.srcdir, self.dist.nick, self.name + '-comps.xml')
            if os.path.isfile(groupfile):
                symlink(groupfile, os.path.join(self.wwwdir, 'comps.xml'))
                repoopts = repoopts + ' --groupfile "%s"' % groupfile
            info(2, '%s: Create repomd repository for %s' % (self.dist.nick, self.name))
            ret = run('%s %s %s' % (cf.cmd['createrepo'], repoopts, self.wwwdir))
            if ret:
                raise(mrepoGenerateException('%s failed with return code: %s' % (cf.cmd['createrepo'], ret)))


class mrepoMirrorException(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class mrepoGenerateException(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


def sha1dir(dir):
    "Return sha1sum of a directory"
    files = glob.glob(dir + '/*.rpm')
    files.sort()
    output = ''
    for file in files:
        output = output + os.path.basename(file) + ' ' + str(os.stat(file).st_size) + '\n'
    return sha1hash(output).hexdigest()


def writesha1(file, sha1sum=None):
    "Write out sha1sum"
    repodir = os.path.dirname(file)
    if not sha1sum:
        sha1sum = sha1dir(repodir)
    if not op.dryrun:
        open(file, 'w').write(sha1sum)


def error(level, str):
    "Output error message"
    if level <= op.verbose:
        sys.stderr.write('mrepo: %s\n' % str)


def info(level, str):
    "Output info message"
    if level <= op.verbose:
        sys.stdout.write('%s\n' % str)


def die(ret, str):
    "Print error and exit with errorcode"
    error(0, str)
    sys.exit(ret)


def run(str, dryrun=False):
    "Run command, accept user input, and print output when needed."
    str = 'exec ' + str
    if op.verbose <= 2:
        str = str + ' >/dev/null'
    if not op.dryrun or dryrun:
        info(5, 'Execute: %s' % str)
        return os.system(str)
    else:
        info(1, 'Not execute: %s' % str)


def readfile(file, len=0):
    "Return content of a file"
    if not os.path.isfile(file):
        return None
    if len:
        return open(file, 'r').read(len)
    return open(file, 'r').read()


def writefile(file, str):
    if op.dryrun:
        return
    fd = open(file, 'w')
    fd.write(str)
    fd.close()

_subst_sub = re.compile('\$\{?(\w+)\}?').sub


def substitute(string, vars, recursion=0):
    "Substitute variables from a string"
    if recursion > 10:
        raise RuntimeError, "variable substitution loop"

    def _substrepl(matchobj):
        value = vars.get(matchobj.group(1))
        if value is not None:
            return substitute(value, vars, recursion + 1)
        return matchobj.group(0)

    string = _subst_sub(_substrepl, string)
    return string


def distsort(a, b):
    return cmp(a.nick, b.nick)


def reposort(a, b):
    return cmp(a.name, b.name)


def vercmp(a, b):
    al = a.split('.')
    bl = b.split('.')
    minlen = min(len(al), len(bl))
    for i in range(1, minlen):
        if cmp(al[i], bl[i]) < 0:
            return -1
        elif cmp(al[i], bl[i]) > 0:
            return 1
    return cmp(len(al), len(bl))


def symlinkglob(str, *targets):
    "Symlink files to multiple targets"
    for file in glob.glob(str):
        for target in targets:
            mkdir(target)
            symlink(file, target)


def abspath(path, reference):
    "Make absolute path from reference"
    return os.path.normpath(os.path.join(path, reference))


def relpath(path, reference):
    """Make relative path from reference
       if reference is a directory, it must end with a /"""
    common = os.path.commonprefix([path, reference])
    common = common[0:common.rfind('/') + 1]
    (uncommon, targetName) = os.path.split(reference.replace(common, '', 1))
    if uncommon:
        newpath = []
        for component in uncommon.split('/'):
            newpath.append('..')
        newpath.append(path.replace(common, '', 1))
        return '/'.join(newpath)
    else:
        return path


def symlink(src, dst):
    "Create a symbolic link, force if dst exists"
    if op.dryrun:
        return
    elif os.path.islink(dst):
        if os.path.samefile(src, abspath(os.readlink(dst), src)):
            return
        os.unlink(dst)
    elif os.path.isdir(dst):
        if os.path.isdir(src):
            if os.path.samefile(src, dst):
                return
        else:
            dst = os.path.join(dst, os.path.basename(src))
            symlink(src, dst)
            return
    elif os.path.isfile(dst):
        if os.path.samefile(src, dst):
            return
        os.rename(dst, dst + '.mrepobak')

    src = relpath(src, dst)

    if not os.path.isdir(os.path.dirname(dst)):
        mkdir(os.path.dirname(dst))
    os.symlink(src, dst)


def copy(src, dst):
    "Copy a file, force if dst exists"
    if op.dryrun:
        return
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    if os.path.islink(dst) or os.path.isfile(dst):
        os.unlink(dst)
    mkdir(os.path.dirname(dst))
    if not os.path.exists(dst):
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst)


def remove(file):
    "Remove files or directories"
    if isinstance(file, types.StringType):
        if op.dryrun:
            return
        if os.path.islink(file):
            os.unlink(file)
        elif os.path.isdir(file):
            try:
                os.rmdir(file)
            except:
                os.path.walk(file, removedir, ())
                os.rmdir(file)
        elif os.path.isfile(file) or os.path.islink(file):
            os.unlink(file)
    else:
        for f in file:
            remove(f)


def removedir(void, dir, files):
    for file in files:
        remove(os.path.join(dir, file))


def mkdir(path):
    "Create a directory, and parents if needed"
    if op.dryrun:
        return
    if os.path.islink(path):
        os.unlink(path)
    if not os.path.exists(path):
        os.makedirs(path)


def mirrorrsync(url, path):
    "Mirror everything from an rsync:// URL"
    if not cf.cmd['rsync']:
        error(1, 'rsync was not found. rsync support is therefore disabled.')
        return

    # Ensure both source and destination paths end with a trailing slash
    url = url.rstrip('/') + '/'
    path = os.path.join(path, '')

    mkdir(path)

    opts = cf.rsyncoptions
    if op.verbose <= 2:
        opts = opts + ' -q'
    elif op.verbose == 3:
        opts = opts + ' -v'
    elif op.verbose == 4:
        opts = opts + ' -v --progress'
    elif op.verbose == 5:
        opts = opts + ' -vv --progress'
    elif op.verbose >= 6:
        opts = opts + ' -vvv --progress'
    if op.dryrun:
        opts = opts + ' --dry-run'
    if cf.rsynctimeout:
        opts = opts + ' --timeout=%s' % cf.rsynctimeout
    if cf.rsynccleanup:
        opts = opts + ' --delete-after --delete-excluded'
    if cf.rsyncbwlimit:
        opts = opts + ' --bwlimit=%s' % cf.rsyncbwlimit
    if cf.rsyncexclheaders:
        opts = opts + ' --exclude=\"/headers/\"'
    if cf.rsyncexclrepodata:
        opts = opts + ' --exclude=\"/repodata/\"'
    if cf.rsyncexclsrpm:
        opts = opts + ' --exclude=\"*.src.rpm\" --exclude=\"/SRPMS/\"'
    if cf.rsyncexcldebug:
        opts = opts + ' --exclude=\"*-debuginfo-*.rpm\" --exclude=\"/debug/\"'
    opts = opts + ' --include=\"*.rpm\"'
    if cf.rsyncexclsrpm or cf.rsyncexcldebug:
        opts = opts + ' --exclude=\"*.*\"'

    ret = run('%s %s %s %s' % (cf.cmd['rsync'], opts, url, path), dryrun=True)
    if ret:
        raise(mrepoMirrorException('Failed with return code: %s' % ret))


def mirrorlftp(url, path, dist):
    "Mirror everything from a http://, ftp://, sftp://, fish:// URL"
    if not cf.cmd['lftp']:
        error(1, 'lftp was not found. fish, ftp, http and sftp support (using lftp) is therefore disabled.')
        return
    mkdir(path)

    cmds = cf.lftpcommands + ';'

    if dist.sslcert:
        cmds = cmds + ' set ssl:cert-file ' + dist.sslcert + ';'
    if dist.sslkey:
        cmds = cmds + ' set ssl:key-file ' + dist.sslkey + ';'
    if dist.sslca:
        cmds = cmds + ' set ssl:ca-file ' + dist.sslca + ' ;'

    if cf.lftptimeout:
        cmds = cmds + ' set net:timeout %s;' % cf.lftptimeout
    if cf.lftpbwlimit:
        cmds = cmds + ' set net:limit-total-rate %s:0;' % cf.lftpbwlimit

    opts = cf.lftpoptions
    if op.verbose >= 6:
        opts = opts + ' -d'

    mirroropts = cf.lftpmirroroptions
    if op.verbose >= 3:
        mirroropts = mirroropts + ' -v' * (op.verbose - 2)
    if op.dryrun:
        mirroropts = mirroropts + ' --dry-run'
    if cf.lftpcleanup:
        mirroropts = mirroropts + ' -e'
    mirroropts = mirroropts + ' -I *.rpm -X \"/headers/\" -X \"/repodata/\"'
    if cf.lftpexclsrpm:
        mirroropts = mirroropts + ' -X \"*.src.rpm\" -X \"/SRPMS/\"'
    if cf.lftpexcldebug:
        mirroropts = mirroropts + ' -X \"*-debuginfo-*.rpm\" -X \"/debug/\"'

    ret = run('%s %s -c \'%s mirror %s %s %s\'' % (cf.cmd['lftp'], opts, cmds, mirroropts, url, path), dryrun=True)
    if ret:
        raise(mrepoMirrorException('Failed with return code: %s' % ret))


def mirrorreposync(url, path, reponame, dist):
    "Mirror everything from a reposync:// URL"
    if not cf.cmd['reposync']:
        error(1, 'reposync was not found. reposync support is therefore disabled.')
        return
    mkdir(path)

    url = url.replace('reposyncs://', 'https://')
    url = url.replace('reposync://', 'http://')
    url = url.replace('reposyncf://', 'ftp://')

    opts = cf.reposyncoptions
    if op.verbose < 3:
        opts = opts + ' -q'
    if op.dryrun:
        opts = opts + ' --urls'
    if cf.reposynccleanup:
        opts = opts + ' --delete'
    if cf.reposyncnewestonly:
        opts = opts + ' --newest-only'
    if cf.reposyncnorepopath:
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
    if cf.reposynctimeout:
    	reposync_conf_contents += "timeout=%s\n" % cf.reposynctimeout
    if cf.reposyncminrate:
    	reposync_conf_contents += "minrate=%s\n" % cf.reposyncminrate


    (fd, reposync_conf_file) = tempfile.mkstemp(text=True)
    handle = os.fdopen(fd, 'w')
    handle.writelines(reposync_conf_contents)
    handle.close()

    ret = run("%s %s --metadata-path %s/reposync --config '%s' --repoid %s --download-path '%s'" % \
              (cf.cmd['reposync'], opts, cf.cachedir, reposync_conf_file, reponame, path))

    # remove the temporary config
    os.remove(reposync_conf_file)

    if ret:
        raise(mrepoMirrorException('Failed with return code: %s' % ret))


def which(cmd):
    "Find executables in PATH environment"
    for path in os.environ.get('PATH', '$PATH').split(':'):
        if os.path.isfile(os.path.join(path, cmd)):
            info(5, 'Found command %s in path %s' % (cmd, path))
            return os.path.join(path, cmd)
    return ''


def mail(subject, msg):
    info(2, 'Sending mail to: %s' % cf.mailto)
    try:
        import smtplib
        smtp = smtplib.SMTP(cf.smtpserver)
        msg = 'Subject: [mrepo] %s\nX-Mailer: mrepo %s\n\n%s' % (subject, VERSION, msg)
        for email in cf.mailto.split():
            smtp.sendmail(cf.mailfrom, email, 'To: %s\n%s' % (email, msg))
        smtp.quit()
    except:
        info(1, 'Sending mail via %s failed.' % cf.smtpserver)


def readconfig():
    cf = Config()
    if cf.confdir and os.path.isdir(cf.confdir):
        files = glob.glob(os.path.join(cf.confdir, '*.conf'))
        files.sort()
        for configfile in files:
            cf.read(configfile)
            cf.update()
    return cf


def _nextNone(iterator):
    try:
        return iterator.next()
    except StopIteration:
        return None


def synciter(a, b, key=None, keya=None, keyb=None):
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
    ai = iter(a)
    bi = iter(b)
    aelem = _nextNone(ai)
    belem = _nextNone(bi)
    while not ((aelem is None) or (belem is None)):
        akey = keya(aelem)
        bkey = keyb(belem)
        if akey == bkey:
            yield aelem, belem
            aelem = _nextNone(ai)
            belem = _nextNone(bi)
        elif akey > bkey:
            # belem missing in a
            yield None, belem
            belem = _nextNone(bi)
        elif bkey > akey:
            # aelem missing in b
            yield aelem, None
            aelem = _nextNone(ai)
    # rest
    while aelem is not None:
        akey = key(aelem)
        yield aelem, None
        aelem = _nextNone(ai)
    while belem is not None:
        bkey = key(belem)
        yield None, belem
        belem = _nextNone(bi)


def listrpms(dirs, relative=''):
    """return a list of rpms in the given directories as a list of (name, path) tuples
    if relative is specified, return the paths relative to this directory"""
    if not isinstance(dirs, (list, tuple)):
        dirs = (dirs,)
    if relative and not relative.endswith('/'):
        relative += '/'
    isdir = os.path.isdir
    pathjoin = os.path.join
    pathexists = os.path.exists

    def processdir(rpms, path, files):
        if relative:
            path2 = relpath(path, relative)
        else:
            path2 = path
        for f in files:
            pf = pathjoin(path, f)
            if f.endswith('.rpm') and pathexists(pf) and not isdir(pf):
                rpms.append((f, path2))

    rpms = []
    for dir in dirs:
        if not dir.startswith('/'):
            dir = pathjoin(relative, dir)
        os.path.walk(dir, processdir, rpms)
    rpms.sort()
    return rpms


def listrpmlinks(dir):
    islink = os.path.islink
    readlink = os.readlink
    pathjoin = os.path.join
    links = []
    for f in os.listdir(dir):
        path = pathjoin(dir, f)
        if islink(path) and f.endswith('.rpm'):
            links.append((f, readlink(path)))
    return links


def main():
    ### Check availability of commands
    for cmd in cf.cmd.keys():
        if not cf.cmd[cmd]:
            continue
        cmdlist = cf.cmd[cmd].split()
        if not os.path.isfile(cmdlist[0]):
            cmdlist[0] = which(cmdlist[0])
        if cmdlist[0] and not os.path.isfile(cmdlist[0]):
            error(4, '%s command not found as %s, support disabled' % (cmd, cmdlist[0]))
            cf.cmd[cmd] = ''
        else:
            cf.cmd[cmd] = ' '.join(cmdlist)
    if not cf.cmd['createrepo']:
        error(1, 'No tools found to generate repository metadata. Please install createrepo.')

    ### Set proxy-related environment variables
    if cf.no_proxy:
        os.environ['no_proxy'] = cf.no_proxy
    if cf.ftp_proxy:
        os.environ['ftp_proxy'] = cf.ftp_proxy
    if cf.http_proxy:
        os.environ['http_proxy'] = cf.http_proxy
    if cf.https_proxy:
        os.environ['https_proxy'] = cf.https_proxy
    if cf.RSYNC_PROXY:
        os.environ['RSYNC_PROXY'] = cf.RSYNC_PROXY

    ### Select list of distributions in order of appearance
    if not op.dists:
        dists = cf.dists
    else:
        dists = []
        for name in op.dists:
            append = False
            for dist in cf.alldists:
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
        if op.update:
            msg = msg + '\n\nDist: %s (%s)' % (dist.name, dist.nick)
            info(1, '%s: Updating %s' % (dist.nick, dist.name))

            distnew = 0
            distremoved = 0

            ### Downloading things
            for repo in dist.listrepos(op.repos):
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
                    info(2, '%s: Repository %s changed (new: %d, removed: %d)' % (dist.nick, repo.name, len(new), len(removed)))
                    fd = open(cf.logfile, 'a+')
                    date = time.strftime("%b %d %H:%M:%S", time.gmtime())

                    def sortedlist(pkgs):
                        l = list(pkgs)
                        l.sort()
                        return l

                    def formatlist(pkglist):
                        return '\n\t' + '\n\t'.join([elem[0] for elem in pkglist])

                    if new:
                        pkglist = sortedlist(new)
                        info(4, '%s: New packages: %s' % (dist.nick, formatlist(pkglist)))
                        distnew += len(pkglist)
                        for element in pkglist:
                            fd.write('%s %s/%s Added %s (%d kiB)\n' % (date, dist.nick, repo.name, element[0], element[1] / 1024))
                            msg = msg + '\n\t\t+ %s (%d kiB)' % (element[0], element[1] / 1024)

                    if removed:
                        pkglist = sortedlist(removed)
                        info(4, '%s: Removed packages: %s' % (dist.nick, formatlist(pkglist)))
                        distremoved += len(pkglist)
                        for element in pkglist:
                            fd.write('%s %s/%s Removed %s (%d kiB)\n' % (date, dist.nick, repo.name, element[0], element[1] / 1024))
                            msg = msg + '\n\t\t- %s (%d kiB)' % (element[0], element[1] / 1024)

                    fd.close()
                    repo.changed = True

            if distnew or distremoved:
                msg = msg + '\n'
                info(1, '%s: Distribution updated (new: %d, removed: %d)' % (dist.nick, distnew, distremoved))
                sumnew = sumnew + distnew
                sumremoved = sumremoved + distremoved

    if sumnew or sumremoved:
        subject = 'changes to %s (new: %d, removed: %d)' % (os.uname()[1], sumnew, sumremoved)
        mail(subject, msg)

    if not op.generate:
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
    exitcode = 0

    op = Options(sys.argv[1:])
    cf = readconfig()
    try:
        main()
    except KeyboardInterrupt, e:
        die(6, 'Exiting on user request')
    sys.exit(exitcode)

# vim:ts=4:sw=4:et
