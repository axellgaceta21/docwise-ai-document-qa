import io
import json

import pymupdf
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_compare_endpoint():
    response = client.post('/api/compare', files={
        'reference': ('reference.pdf', io.BytesIO(pdf('Design pressure: 150 kPa.')), 'application/pdf'),
        'submitted': ('submitted.pdf', io.BytesIO(pdf('Design pressure: 120 kPa.')), 'application/pdf')},
        data={'checklist': json.dumps([{'id': 'R-01', 'title': 'Pressure', 'reference_text': 'Design pressure: 150 kPa.'}])})
    assert response.status_code == 200
    assert response.json()['findings'][0]['status'] == 'different'
    assert response.json()['findings'][0]['reference']['page'] == 1


def test_rejects_non_pdf():
    response = client.post('/api/compare', files={
        'reference': ('reference.pdf', b'not a pdf', 'application/pdf'),
        'submitted': ('submitted.pdf', pdf('Test'), 'application/pdf')},
        data={'checklist': json.dumps([{'id': 'R-01', 'title': 'Test', 'reference_text': 'Test'}])})
    assert response.status_code == 400


def test_rejects_duplicate_ids():
    item = {'id': 'R-01', 'title': 'Test', 'reference_text': 'Test'}
    response = client.post('/api/compare', files={
        'reference': ('reference.pdf', pdf('Test'), 'application/pdf'),
        'submitted': ('submitted.pdf', pdf('Test'), 'application/pdf')},
        data={'checklist': json.dumps([item, item])})
    assert response.status_code == 422
