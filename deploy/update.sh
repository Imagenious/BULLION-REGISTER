#!/bin/bash
# Update Bullion Register on PythonAnywhere to the latest version on GitHub.
# Run in a PythonAnywhere Bash console:   bash ~/BULLION-REGISTER/deploy/update.sh
# Your records (instance/bullion.db) are never touched by an update; a safety copy is made first anyway.
set -e
cd ~/BULLION-REGISTER

mkdir -p ~/db-backups
if [ -f instance/bullion.db ]; then
  cp instance/bullion.db ~/db-backups/bullion-$(date +%Y-%m-%d-%H%M).db
  ls -1t ~/db-backups/*.db | tail -n +31 | xargs -r rm --   # keep the 30 most recent copies
  echo "Safety copy of your data saved in ~/db-backups"
fi

git pull --ff-only
~/.venvs/bullion/bin/pip install -q -r requirements.txt
touch /var/www/bullionregister_pythonanywhere_com_wsgi.py   # tells PythonAnywhere to restart the app

echo "UPDATED - the new version is live and your data was not changed"
