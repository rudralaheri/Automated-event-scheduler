import os
import json
import base64
import webbrowser
import re

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool


#config
BASE_DIR         = Path(__file__).parent
TOKEN_FILE       = BASE_DIR / "token.json"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
INBOX_FILE       = BASE_DIR / "pending_review.html"
LOG_FILE         = BASE_DIR / "agent.log"
EMAILS_TO_SCAN   = 10
