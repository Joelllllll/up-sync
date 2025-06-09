import glob
import json

import requests


def upload_mockserver_expectations(expectations: list):
    for exp in expectations:
        resp = requests.put(
            'http://mockserver:1080/mockserver/expectation',
            headers={"Content-Type": "application/json"},
            json={
            "httpRequest": exp["httpRequest"],
            "httpResponse": exp["httpResponse"]
            }
        )
        assert resp.status_code == 201, resp.text

print('resetting mockserver')
requests.put('http://mockserver:1080/mockserver/reset')

for file_path in glob.glob("config/mockserver/*.json"):
    with open(file_path, "r") as file:
        data = json.load(file)
        upload_mockserver_expectations(data)
