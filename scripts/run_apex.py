#!/usr/bin/env python3
"""Entrypoint: boots the full Garcar Apex Orchestrator.
   python scripts/run_apex.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.apex_orchestrator import ApexOrchestrator
import asyncio
import signal

apex = ApexOrchestrator()
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def _stop(*args):
    for task in asyncio.all_tasks(loop):
        task.cancel()

for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, _stop)

try:
    loop.run_until_complete(apex.run())
finally:
    loop.close()
