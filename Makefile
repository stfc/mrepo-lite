name = mrepo
version = $(shell awk '/^Version: / {print $$2}' $(name).spec)
date = $(shell date +%Y%m%d%H%M)

### Get the branch information from git
git_ref = $(shell git symbolic-ref -q HEAD)
git_branch ?= $(lastword $(subst /, ,$(git_ref)))
git_branch ?= HEAD

prefix = /usr
sysconfdir = /etc
bindir = $(prefix)/bin
sbindir = $(prefix)/sbin
libdir = $(prefix)/lib
datadir = $(prefix)/share
mandir = $(datadir)/man
localstatedir = /var

cachedir = $(localstatedir)/cache/mrepo


all:
	@echo "There is nothing to be build. Try install !"

docs:
	make -C docs

dist: clean
	sed -i \
		-e 's#^Source:.*#Source: $(name)-$(distversion).tar.bz2#' \
		-e 's#^Version:.*#Version: $(version)#' \
		-e 's#^\(Release: *[0-9]\+\)#\1$(rpmrelease)#' \
		$(name).spec
	git ls-tree -r --name-only --full-tree $(git_branch) | \
		tar -cjf $(name)-$(distversion).tar.bz2 --transform='s,^,$(name)-$(version)/,S' --files-from=-
	git checkout $(name).spec

rpm: dist
	rpmbuild -tb --clean --rmspec \
		--define "_rpmfilename %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm" \
		--define "debug_package %{nil}" \
		--define "_rpmdir %(pwd)" \
		$(name)-$(distversion).tar.bz2

srpm: dist
	rpmbuild -ts --clean --rmsource --rmspec \
		--define "_rpmfilename %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm" \
		--define "_srcrpmdir ../" \
		$(name)-$(distversion).tar.bz2

clean:
	rm -f README*.html
