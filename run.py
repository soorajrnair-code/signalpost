#!/usr/bin/env python3
"""
SignalPost: Autonomous Norwegian Company Intelligence Agent
Single-command runner for Unstop & Builderr.ai hackathon submission.

Usage:
  py run.py --orgnr 923609016
  py run.py --query "Equinor"
  py run.py --benchmark
  py run.py --harvest 1000
  py run.py --serve
"""

import sys
from signalpost.cli import main

if __name__ == "__main__":
    main()
