"""Monitor GitHub Actions workflow runs for this repository and optionally send Slack notifications.

Usage:
  python scripts/monitor_ci.py [--latest] [--notify]

Environment:
  GITHUB_TOKEN (optional) - provides higher rate limits if present
  SLACK_WEBHOOK_URL (optional) - if --notify is used, must be set to post to Slack
"""

import os
import sys
import urllib.request
import json
import argparse

REPO = 'nervhuang/FileManager'
API_URL = f'https://api.github.com/repos/{REPO}/actions/runs?per_page=10'


def fetch_runs(token=None):
    req = urllib.request.Request(API_URL)
    if token:
        req.add_header('Authorization', f'token {token}')
    with urllib.request.urlopen(req) as resp:
        return json.load(resp).get('workflow_runs', [])


def print_runs(runs):
    for r in runs:
        print(f"id:{r.get('id')} status:{r.get('status')} conclusion:{r.get('conclusion')} event:{r.get('event')} url:{r.get('html_url')}")


def send_slack(message, webhook):
    payload = json.dumps({'text': message}).encode('utf-8')
    req = urllib.request.Request(webhook, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--latest', action='store_true', help='Only print the latest run')
    p.add_argument('--notify', action='store_true', help='Send a Slack notification for the latest run (requires SLACK_WEBHOOK_URL)')
    args = p.parse_args()

    token = os.environ.get('GITHUB_TOKEN')
    webhook = os.environ.get('SLACK_WEBHOOK_URL')

    runs = fetch_runs(token)
    if not runs:
        print('No runs found')
        return 1

    if args.latest:
        run = runs[0]
        print_runs([run])
        if args.notify:
            if not webhook:
                print('SLACK_WEBHOOK_URL not set')
                return 2
            message = f"Workflow {run.get('name')} concluded with {run.get('conclusion')}. {run.get('html_url')}"
            send_slack(message, webhook)
            print('Sent slack notification')
    else:
        print_runs(runs)
    return 0


if __name__ == '__main__':
    sys.exit(main())