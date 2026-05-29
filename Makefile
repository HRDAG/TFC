# Author: PB and Claude
# Date: 2026-05-29
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# Makefile
#
# Install/operate the single-machine tfcs-monitor collector on scott.
# NOT ansible-managed: this is one tool on one host.
#
# `make install` figures out where it's running:
#   - ON scott            -> install/cp locally with sudo
#   - anywhere else (porky, the usual case) -> scp the files over, then
#     ssh + sudo to place them
#
# Cutover (one time), watch each step:
#   make migrate              # seed the new path with the existing series
#   make install              # deploy binary + units + data dir, enable timer
#   make verify               # confirm the new timer is producing snapshots
#   make disable-old-cron     # remove the legacy root crontab line (backs up first)
#
# migrate is an order-independent dedup-merge, so running it before or after
# install is safe; the analyzer sorts by ts regardless of line order.

TARGET   ?= scott
HOSTSHORT := $(shell hostname -s)
ifeq ($(HOSTSHORT),scott)
ON_SCOTT := yes
else
ON_SCOTT := no
endif

BIN        := /usr/local/bin/tfcs-monitor
DATADIR    := /var/lib/tfcs-monitor
SERIES     := $(DATADIR)/replication-progress.jsonl
OLD_SERIES := /var/log/tfcs/replication-progress.jsonl
UNITDIR    := /etc/systemd/system

.PHONY: help install install-local install-remote migrate migrate-local \
        migrate-remote verify disable-old-cron where

help:  ## Show targets
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sort | \
	    awk 'BEGIN{FS=":.*?## "}{printf "  %-20s %s\n", $$1, $$2}'

where:  ## Print whether this run installs locally or over ssh
	@echo "hostname -s = $(HOSTSHORT) -> ON_SCOTT=$(ON_SCOTT); TARGET=$(TARGET)"

install:  ## Deploy collector + systemd units, enable the timer
ifeq ($(ON_SCOTT),yes)
	@$(MAKE) --no-print-directory install-local
else
	@$(MAKE) --no-print-directory install-remote
endif

install-local:
	sudo install -m 0755 scripts/tfcs-monitor $(BIN)
	sudo install -d -o tfcs -g tfcs -m 0755 $(DATADIR)
	sudo install -m 0644 deploy/tfcs-monitor.service $(UNITDIR)/tfcs-monitor.service
	sudo install -m 0644 deploy/tfcs-monitor.timer   $(UNITDIR)/tfcs-monitor.timer
	sudo systemctl daemon-reload
	sudo systemctl enable --now tfcs-monitor.timer
	@systemctl list-timers tfcs-monitor.timer --no-pager || true

install-remote:
	scp scripts/tfcs-monitor deploy/tfcs-monitor.service deploy/tfcs-monitor.timer $(TARGET):/tmp/
	ssh $(TARGET) 'set -e; \
	  sudo install -m 0755 /tmp/tfcs-monitor $(BIN); \
	  sudo install -d -o tfcs -g tfcs -m 0755 $(DATADIR); \
	  sudo install -m 0644 /tmp/tfcs-monitor.service $(UNITDIR)/tfcs-monitor.service; \
	  sudo install -m 0644 /tmp/tfcs-monitor.timer   $(UNITDIR)/tfcs-monitor.timer; \
	  sudo systemctl daemon-reload; \
	  sudo systemctl enable --now tfcs-monitor.timer; \
	  rm -f /tmp/tfcs-monitor /tmp/tfcs-monitor.service /tmp/tfcs-monitor.timer; \
	  systemctl list-timers tfcs-monitor.timer --no-pager'

migrate:  ## One-time: seed /var/lib series from /var/log (dedup-merge, order-safe)
ifeq ($(ON_SCOTT),yes)
	@$(MAKE) --no-print-directory migrate-local
else
	@$(MAKE) --no-print-directory migrate-remote
endif

migrate-local:
	sudo install -d -o tfcs -g tfcs -m 0755 $(DATADIR)
	sudo -u tfcs bash -c 'cat $(OLD_SERIES) $(SERIES) 2>/dev/null | sort -u > $(SERIES).merge && mv $(SERIES).merge $(SERIES)'
	@sudo -u tfcs wc -l $(SERIES)

migrate-remote:
	ssh $(TARGET) 'sudo install -d -o tfcs -g tfcs -m 0755 $(DATADIR); \
	  sudo -u tfcs bash -c "cat $(OLD_SERIES) $(SERIES) 2>/dev/null | sort -u > $(SERIES).merge && mv $(SERIES).merge $(SERIES)"; \
	  sudo -u tfcs wc -l $(SERIES)'

verify:  ## Show timer schedule + last lines of the new series
	ssh $(TARGET) 'systemctl list-timers tfcs-monitor.timer --no-pager; \
	  echo ---; sudo -u tfcs tail -2 $(SERIES) 2>/dev/null | cut -c1-120'

disable-old-cron:  ## Remove the legacy root crontab line (backs up to /tmp first)
	ssh $(TARGET) 'sudo crontab -l | sudo tee /tmp/root-crontab.bak >/dev/null; \
	  echo "backed up root crontab -> /tmp/root-crontab.bak"; \
	  sudo crontab -l | grep -v "replication-progress" | sudo crontab -; \
	  echo "remaining tfcs/replication lines:"; \
	  sudo crontab -l | grep -iE "tfcs|replication" || echo "  (none)"'
