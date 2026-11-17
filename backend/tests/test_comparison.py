from app.comparison import compare, normalize
from app.models import Requirement
from app.pdf import PageText


def test_normalization_ignores_case_and_punctuation():
    assert normalize("Design pressure: 150 kPa.") == normalize("DESIGN PRESSURE 150 kPa")


def test_comparison_reports_match_difference_and_missing_with_real_citations():
    reference = [PageText(2, "Design pressure: 150 kPa.\nPipe material: ASTM A106 Grade B carbon steel.\nInspection method: visual inspection and hydrostatic test.")]
    submitted = [PageText(3, "Design pressure: 120 kPa.\nPipe material: ASTM A106 Grade B carbon steel.")]
    checklist = [Requirement(id="1", title="Pressure", reference_text="Design pressure: 150 kPa."),
                 Requirement(id="2", title="Material", reference_text="Pipe material: ASTM A106 Grade B carbon steel."),
                 Requirement(id="3", title="Inspection", reference_text="Inspection method: visual inspection and hydrostatic test.")]
    findings = compare(reference, submitted, checklist)
    assert [f.status for f in findings] == ["different", "match", "missing"]
    assert findings[0].reference and findings[0].reference.page == 2
    assert findings[0].submitted and findings[0].submitted.page == 3
    assert findings[2].submitted is None


def test_unverified_reference_has_no_invented_citation():
    finding = compare([PageText(1, "Unrelated text")], [PageText(1, "Other text")],
        [Requirement(id="1", title="Pressure", reference_text="Design pressure: 150 kPa.")])[0]
    assert finding.status == "reference_missing"
    assert finding.reference is None and finding.submitted is None
