name = mrepo-lite
version = $(shell git describe --dirty --broken)
date = $(shell date +%Y%m%d%H%M)

prefix = /usr
sysconfdir = /etc
bindir = $(prefix)/bin
sbindir = $(prefix)/sbin
libdir = $(prefix)/lib
datadir = $(prefix)/share
mandir = $(datadir)/man
localstatedir = /var

cachedir = $(localstatedir)/cache/mrepo
docdir = $(datadir)/doc/$(name)-$(version)

.PHONY: all
all: clean rpm deb

docs:
	make -C docs

dist:
	mkdir -p dist/mrepo.conf.d dist/cache
	cp -f mrepo.py dist/mrepo
	sed -i 's/#version#/$(version)/' dist/mrepo

.PHONY: package-%
package-%: dist
	fpm \
		--verbose \
		\
		--input-type dir \
		--output-type "$(lastword $(subst -, ,$@))" \
		--package dist/ \
		\
		--name "$(name)" \
		--version "$(version)" \
		--iteration 1 \
		--license GPL \
		--epoch "$(shell date +%s)" \
		--architecture noarch \
		--vendor 'Science and Technology Facilties Council' \
		--url 'https://github.com/stfc/mrepo-lite' \
		--description 'mrepo-lite is a tool for mirroring upstream software repositories.' \
		--category 'System Environment/Base' \
		\
		--depends 'createrepo' \
		--depends 'python >= 2.7' \
		--conflicts yam \
		--conflicts mrepo \
		\
		--config-files $(sysconfdir)/cron.d/mrepo \
		--config-files $(sysconfdir)/logrotate.d/mrepo \
		--config-files $(sysconfdir)/mrepo.conf \
		--config-files $(sysconfdir)/mrepo.conf.d \
		\
		--directories $(sysconfdir)/mrepo.conf.d \
		--directories $(docdir) \
		--directories $(cachedir) \
		\
		dist/mrepo=$(bindir)/mrepo \
		dist/cache=$(cachedir) \
		dist/mrepo.conf.d=$(sysconfdir)/ \
		config/mrepo.conf=$(sysconfdir)/mrepo.conf \
		config/mrepo.cron=$(sysconfdir)/cron.d/mrepo \
		config/mrepo.logrotate=$(sysconfdir)/logrotate.d/mrepo \
		\
		config/mrepo-example.conf=$(docdir)/ \
		config/mrepo-complex.conf=$(docdir)/ \
		docs/=$(docdir) \
		AUTHORS=$(docdir) \
		ChangeLog=$(docdir) \
		COPYING=$(docdir) \
		README=$(docdir) \
		THANKS=$(docdir) \
		TODO=$(docdir)

.PHONY: rpm
rpm: package-rpm

.PHONY: deb
deb: package-deb

.PHONY: clean
clean:
	rm -f README*.html
	rm -rf dist/
