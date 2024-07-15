#!/usr/bin/python2

import os
import sys

import os.path
import unittest
from shutil import rmtree
from tempfile import mkdtemp

import mrepo


class TestSync(unittest.TestCase):
    def setUp(self):
        pass
    def test_synciter1(self):
        left = (
            1, 2, 4, 5
            )
        right = (
            2, 3, 5, 6, 7
            )

        onlyright = []
        onlyleft = []
        keyequal = []
        for a, b in mrepo.synciter(left, right):
            if a is None:
                onlyright.append(b)
            elif b is None:
                onlyleft.append(a)
            else:
                keyequal.append(a)

        self.assertEqual(onlyright, [3, 6, 7])
        self.assertEqual(onlyleft, [1, 4])
        self.assertEqual(keyequal, [2, 5])

    def test_synciter2(self):
        left = (
            (1, 'l1'), (2, 'l2'), (4, 'l4'), (5, 'l5')
            )
        right = (
            (2, 'r2'), (3, 'r3'), (5, 'r5'), (6, 'r6'), (7, 'r7')
            )

        onlyright = []
        onlyleft = []
        keyequal = []
        # key is the first element
        for a, b in mrepo.synciter(left, right, key = lambda x: x[0]):
            if a is None:
                onlyright.append(b)
            elif b is None:
                onlyleft.append(a)
            else:
                keyequal.append((a, b))

        self.assertEqual(onlyright, [(3, 'r3'), (6, 'r6'), (7, 'r7')])
        self.assertEqual(onlyleft, [(1, 'l1'), (4, 'l4')])
        self.assertEqual(keyequal, [((2, 'l2'), (2, 'r2')),
                                    ((5, 'l5'), (5, 'r5'))])


class Testlinksync(unittest.TestCase):
    def setUp(self):
        pj = os.path.join

        self.tmpdir = tmpdir = mkdtemp(prefix='mrepo_tests_')

        class TestConfig:
            pass

        self.cf = cf = TestConfig()

        cf.srcdir = pj(tmpdir, 'src')
        cf.wwwdir = pj(tmpdir, 'dst')

        self.dist = mrepo.Dist('testdist', 'i386', cf)
        self.repo = repo = mrepo.Repo('testrepo', '', self.dist, cf)
        srcdir = repo.srcdir


        # tmp/src/testdist-i386/testrepo
        os.makedirs(srcdir)

        # tmp/dst/testdist-i386/RPMS.testrepo
        os.makedirs(repo.wwwdir)

        for f in xrange(4):
            __touch(pj(srcdir, str(f) + '.rpm'))
        __touch(pj(srcdir, 'dontsync.txt'))

        os.mkdir(pj(srcdir, 'a'))
        __touch(pj(srcdir, 'a', '2.rpm'))
        __touch(pj(srcdir, 'a', 'a.rpm'))

        self.localdir = localdir = pj(cf.srcdir, 'testdist-i386', 'local')
        os.makedirs(localdir)
        for f in ('local.rpm', 'dont_sync2.txt'):
            __touch(pj(localdir, f))

        # this should be the result when linksync'ing srcdir
        self.linkbase = linkbase = '../../../src/testdist-i386/testrepo'
        self.links = [
            ('0.rpm', pj(linkbase, '0.rpm')),
            ('1.rpm', pj(linkbase, '1.rpm')),
            ('2.rpm', pj(linkbase, '2.rpm')),
            ('3.rpm', pj(linkbase, '3.rpm')),
            ('a.rpm', pj(linkbase, 'a', 'a.rpm'))
            ]
        self.links.sort()

    def tearDown(self):
        tmpdir = self.tmpdir

        # for safety-reasons:
        if tmpdir.count('/') < 2:
            raise Exception("Will not remove tmpdir %s" % ( tmpdir, ))

        rmtree(tmpdir)

    def readlinks(self, dir):
        """return a list of (linkname, linktarget) tuples for all files in a directory"""
        pj = os.path.join
        readlink = os.readlink
        result = [ (l, readlink(pj(dir, l))) for l in os.listdir(dir) ]
        result.sort()
        return result

    def genlinks(self, links, dir=''):
        if not dir:
            dir = self.repo.wwwdir
        pj = os.path.join
        symlink = os.symlink
        for name, target in links:
            symlink(target, pj(dir, name))

    def test_listrpms(self):
        srcdir = self.repo.srcdir
        actual = mrepo.listrpms(srcdir)
        pj= os.path.join
        target = [
            ('0.rpm', srcdir),
            ('1.rpm', srcdir),
            ('2.rpm', srcdir),
            ('2.rpm', pj(srcdir, 'a')),
            ('3.rpm', srcdir),
            ('a.rpm', pj(srcdir, 'a')),
            ]
        self.assertEqual(actual, target)

    def test_listrpms_rel(self):
        srcdir = self.repo.srcdir
        linkbase = self.linkbase
        actual = mrepo.listrpms(srcdir, relative = self.repo.wwwdir)
        pj= os.path.join
        target = [
            ('0.rpm', linkbase),
            ('1.rpm', linkbase),
            ('2.rpm', linkbase),
            ('2.rpm', pj(linkbase, 'a')),
            ('3.rpm', linkbase),
            ('a.rpm', pj(linkbase, 'a')),
            ]
        self.assertEqual(actual, target)

    def test_linksync_new(self):
        repo = self.repo
        self.dist.linksync(repo)

        actual = self.readlinks(repo.wwwdir)
        target = self.links
        self.assertEqual(actual, target)

    def test_linksync_missing(self):
        repo = self.repo
        links = self.links[:]

        # remove some links
        del links[0]
        del links[2]
        del links[-1:]
        self.genlinks(links)

        self.dist.linksync(repo)

        actual = self.readlinks(repo.wwwdir)
        target = self.links
        self.assertEqual(actual, target)

    def test_linksync_additional(self):
        repo = self.repo
        links = self.links[:]

        pj = os.path.join
        # add some links
        links.insert(0, ('new1.rpm', pj(self.linkbase, 'new1.rpm')))
        links.insert(2, ('new2.rpm', pj(self.linkbase, 'new2.rpm')))
        links.append(('new3.rpm', pj(self.linkbase, 'new3.rpm')))
        self.genlinks(links)

        self.dist.linksync(repo)

        actual = self.readlinks(repo.wwwdir)
        target = self.links
        self.assertEqual(actual, target)

    def test_linksync_targetchange(self):
        repo = self.repo
        links = self.links[:]

        pj = os.path.join
        # add some links

        # basename != target basename
        links[1] = (links[1][0], pj(self.linkbase, 'illegal.rpm'))
        # different dir
        links[2] = (links[2][0], pj(self.linkbase, 'illegaldir', links[2][0]))
        # correct, but absolute link
        links[3] = (links[3][0], pj(repo.srcdir, links[3][0]))

        self.genlinks(links)

        self.dist.linksync(repo)

        actual = self.readlinks(repo.wwwdir)
        target = self.links
        self.assertEqual(actual, target)


    def test_linksync_mod(self):
        self.dist.linksync(self.repo)

def _Testlinksync__touch(filename):
    open(filename, 'a')


if __name__ == '__main__':
    # mrepo.op = mrepo.Options(('-vvvvv', '-c/dev/null'))
    mrepo.op = mrepo.Options(('-c/dev/null')) # should really get rid of this!
    unittest.main()
