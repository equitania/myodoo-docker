#!/usr/bin/python
# -*- coding: utf-8 -*-
# Alte nginx logs löschen
# Delete old nginx logs
# Version 1.0.0
# Date 12.02.2018

import os
import time

logpath = '/var/log/nginx'

# run by crontab
# removes all logs older than 30 days

# nginx starten
os.system("service nginx stop")

now = time.time()
cutoff = now - (30 * 86400)

# removes any files in mynginxpath older than 14 days
files = os.listdir(logpath + "/")
for xfile in files:
    if os.path.isfile(logpath + "/" + xfile):
        t = os.stat(logpath + "/" + xfile)
        c = t.st_ctime
        
        # delete file if older than 4 weeks
        if c < cutoff:
            #print "remove: " + logpath + "/" + xfile
            os.remove(logpath + "/" + xfile)

# nginx starten
os.system("service nginx start")

