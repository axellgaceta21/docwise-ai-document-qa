"""Generate fictional, non-engineering sample PDFs for local testing."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent


def make(name: str, revision: str, clauses: list[str]) -> None:
    output = ROOT / name
    page = canvas.Canvas(str(output), pagesize=A4)
    width, height = A4
    page.setFillColor(colors.HexColor('#102a4c'))
    page.rect(0, height - 112, width, 112, fill=1, stroke=0)
    page.setFillColor(colors.white)
    page.setFont('Helvetica-Bold', 18)
    page.drawString(48, height - 55, 'Northstar Process Works')
    page.setFont('Helvetica', 9)
    page.drawString(48, height - 78, 'FICTIONAL TRAINING DOCUMENT  |  NOT FOR ENGINEERING USE')
    page.setFillColor(colors.HexColor('#233850'))
    page.setFont('Helvetica-Bold', 16)
    page.drawString(48, height - 156, 'Utility Pipe Specification')
    page.setFont('Helvetica', 10)
    page.setFillColor(colors.HexColor('#71829a'))
    page.drawString(48, height - 177, f'Project: NS-042  |  Revision: {revision}  |  System: Cooling water loop')
    y = height - 228
    for number, clause in enumerate(clauses, 1):
        page.setFillColor(colors.HexColor('#e8eef5'))
        page.rect(48, y - 14, width - 96, 38, fill=1, stroke=0)
        page.setFillColor(colors.HexColor('#2c66ae'))
        page.setFont('Helvetica-Bold', 9)
        page.drawString(60, y + 8, f'{number:02d}')
        page.setFillColor(colors.HexColor('#223650'))
        page.setFont('Helvetica', 10)
        page.drawString(88, y + 8, clause)
        y -= 55
    page.setStrokeColor(colors.HexColor('#d8e1eb'))
    page.line(48, 55, width - 48, 55)
    page.setFont('Helvetica', 8)
    page.setFillColor(colors.HexColor('#8292a6'))
    page.drawString(48, 40, 'Sample data only - all organizations, projects, and values are fictional.')
    page.drawRightString(width - 48, 40, 'Page 1 of 1')
    page.save()


if __name__ == '__main__':
    make('approved_reference.pdf', 'A - Approved', [
        'Design pressure: 150 kPa.',
        'Operating temperature: 80 C.',
        'Pipe material: ASTM A106 Grade B carbon steel.',
        'Inspection method: visual inspection and hydrostatic test.',
    ])
    make('submitted_revision.pdf', 'B - Submitted', [
        'Design pressure: 120 kPa.',
        'Operating temperature: 80 C.',
        'Pipe material: ASTM A106 Grade B carbon steel.',
    ])
