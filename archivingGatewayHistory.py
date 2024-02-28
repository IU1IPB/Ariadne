#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3


"""

This is an utility program useful for reducing the size of Ariade databases by deleting qsos older than two months.
The main JS8call logfile DIRECTED.TXT is also copied as DIRECTED.OLD

"""

import calendar  # timestamp UTC
import configparser  # .ini configuration files library
import datetime  # date & time..
import logging  # log manager
import os
import re  # Regular expression library
import sqlite3  # sqlite3 database library
import sys
import time  # Time date library

from datetime import datetime
# from pathlib import Path  # file path

# common functions
from common_functions import is_database_locked
from common_functions import get_configuration  # lanscape parameters

# Configuration

config = configparser.ConfigParser()  # .ini file manager

#####

logging.basicConfig(filename='ariadne.log', encoding='utf-8', level=logging.WARNING,
                    format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')  # log file manager


##########################################################################
##
#  .ini file read settings
##


# Get configuration parameters from config.ini
configuration = get_configuration()

# Path js8call
js8call_db_path = configuration[1]
js8call_folder = configuration[0]

#####

# Initializing log...
logging.warning('>>> Program : ' + os.path.basename(__file__) + ' started.')

# Get now() time in UTC and convert to Epoch
epoch_timestamp = calendar.timegm(time.gmtime())

##########################################################################


##########################################################################

os.system('clear')
print("\nThis utility program will delete AriadneQSOs data older than one month and will delete DIRECTED.TXT file.")
print("the whole js8call history file .")
print("Do you REALLY want to proceed ?")
answer = input("yes/no : ")

if answer != 'yes':
    print("\nNothing to be done !!")
    sys.exit(0)

#######################

# Copy JS8CALL "DIRECTED.TXT" as "DIRECTED.OLD"

# Importing js8call logfile path...
js8call_log = js8call_folder / "DIRECTED.TXT"

if os.path.exists(js8call_log) is False:

    logging.warning('JS8call log file DIRECTED.TXT already archived.')

else:

    if os.path.exists(js8call_folder / "DIRECTED.OLD") is True:

        os.remove(js8call_folder / "DIRECTED.OLD")
        logging.warning('JS8call log file previous copy DIRECTED.OLD deleted.')

    os.rename(js8call_log, js8call_folder / "DIRECTED.OLD")
    logging.warning('File DIRECTED.TXT renamed to DIRECTED.OLD')

######

# Preliminary checks in db : are trhey locked ?

db = sqlite3.connect("ariadne.db3")
locked = is_database_locked(db)

if locked is True:

    logging.error('Ariadne database is locked : aborted.')
    sys.exit()  # nothing can be done

connection_ariadne = sqlite3.connect("ariadne.db3")

# connection_ariadne= sqlite3.connect("aprs.db3:memory:?cache=shared")
# In memory, to be checked

cursor_ariadne = connection_ariadne.cursor()

cursor_ariadne.execute(

    "CREATE TABLE IF NOT EXISTS qso (time INTEGER NOT NULL, frequency REAL NOT NULL, overlay INTEGER NOT NULL, snr REAL, srccall TEXT NOT NULL, dst TEXT NOT NULL) ")

###############################################################

# Cleaning Ariadne tables : deleting records older than 30 days

archiving_limit = (epoch_timestamp - 3600 * 24 * 30)

params_ariadne = (archiving_limit,)

cursor_ariadne.execute(
    "DELETE FROM qso WHERE time <= ?",
    params_ariadne)
connection_ariadne.commit()


cursor_ariadne.execute(
    "DELETE FROM messages WHERE time <= ?",
    params_ariadne)
connection_ariadne.commit()

logging.warning('Ariadne old messages have been deleted.')

sys.exit()
