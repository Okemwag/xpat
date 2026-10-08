"""Submission documents: reading, parsing, deterministic checks. No network: fake LLM, gazetteer and hazard."""

import io
import zipfile
from decimal import Decimal
import pytest
from floodcat.ai.documents import read_document
from floodcat.ai.submission import (
    build_submission,
    number_in_quote,
    parse_coordinates,
    quote_found,
    to_exposure_row,
)
from floodcat.core.errors import ModelError
from floodcat.exposure.validation import validate_rows
from floodcat.financial.loss import exposed_fraction
from floodcat.services.analysis import analyse
from conftest import row


def make_pdf(lines):
    """Minimal one-page PDF with a text layer (Helvetica), built by hand."""
    content = (
        "BT /F1 11 Tf 50 780 Td 14 TL "
        + " ".join(f"({l.replace('(', '').replace(')', '')}) '" for l in lines)
        + " ET"
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(
        f"{o:010d} 00000 n \n".encode() for o in offsets
    )
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_docx(paragraphs, table=()):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        body += (
            "<w:tbl>"
            + "".join(
                "<w:tr>"
                + "".join(
                    f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r
                )
                + "</w:tr>"
                for r in table
            )
            + "</w:tbl>"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


DOC_LINES = [
    "TEST SUBMISSION - synthetic",
    "GPS COORDINATES: -1.2847°S, 36.8247°E",
    "Address: Upper Hill, Nairobi",
    "CONSTRUCTION CLASSIFICATION: RCC Frame",
    "Total Number of Floors: 18 (above ground) + 2 (basement)",
    "GROSS FLOOR AREA: 24,500 m2",
    "Typical floor: 1,280 m2 each (16 floors)",
    "Ground Floor: 2,150 m2",
    "Flood limit can be set at full TIV (KES 1,090,000,000)",
    "5% deductible or KES 5,000,000 minimum",
    "Kenyatta University (East) - 3.2 km",
    "No flood losses recorded in 11 years",
]


def test_pdf_named_docx_is_read_as_pdf():
    pytest.importorskip("pypdf")
    doc = read_document(make_pdf(DOC_LINES), "OFFER.docx.pdf")
    assert (
        doc["kind"] == "pdf"
        and doc["name_mismatch"]
        and "1,090,000,000" in doc["text"]
        and doc["pages"] == 1
    )


def test_docx_paragraphs_and_tables():
    doc = read_document(
        make_docx(
            ["Landmark Plaza", "RCC frame"], [("Floor", "Area"), ("Ground", "2,150")]
        ),
        "x.docx",
    )
    assert (
        doc["kind"] == "docx"
        and "Ground | 2,150" in doc["text"]
        and not doc["name_mismatch"]
    )


@pytest.mark.parametrize(
    "data,code",
    [
        (b"", "empty_document"),
        (b"\xd0\xcf\x11\xe0" + b"0" * 100, "unsupported_document"),
        (b"PK\x03\x04garbage", "unsupported_document"),
        (b"\x00\x01binary\x00", "unsupported_document"),
    ],
)
def test_unsupported_or_empty_files(data, code):
    with pytest.raises(ModelError) as exc:
        read_document(data, "f")
    assert exc.value.code == code


def test_scanned_pdf_rejected():
    pytest.importorskip("pypdf")
    with pytest.raises(ModelError) as exc:
        read_document(make_pdf([]), "scan.pdf")
    assert exc.value.code == "scanned_document"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("-1.2847°S, 36.8247°E", (-1.2847, 36.8247)),
        ("1.2847 S, 36.8247 E", (-1.2847, 36.8247)),
        ("-1.2847, 36.8247", (-1.2847, 36.8247)),
        ("36.8247°E, 1.2847°S", (-1.2847, 36.8247)),
        ("1°17'05\"S 36°49'29\"E", (-1.284722, 36.824722)),
        ("36.8247, -1.2847", (-1.2847, 36.8247)),
    ],
)
def test_coordinate_parser(text, expected):
    lat, lon, _ = parse_coordinates(text)
    assert lat == pytest.approx(expected[0], abs=1e-5) and lon == pytest.approx(
        expected[1], abs=1e-5
    )


def test_coordinate_parser_rejects_nonsense():
    assert (
        parse_coordinates("near the big tree")[0] is None
        and parse_coordinates(None)[0] is None
    )


def test_quote_and_number_checks():
    text = "Flood limit can be set at\nfull TIV (KES 1,090,000,000) with confidence."
    assert quote_found("full TIV (KES 1,090,000,000)", text) and not quote_found(
        "KES 2,000,000", text
    )
    assert number_in_quote(1.09e9, "full TIV (KES 1,090,000,000)") and number_in_quote(
        1.09e9, "KES 1.09bn"
    )
    assert not number_in_quote(2e9, "full TIV (KES 1,090,000,000)")


class FakeGaz:
    places = {
        "upper hill": {"lat": -1.2941, "lon": 36.8129, "method": "nominatim"},
        "kenyatta university": {"lat": -1.1807, "lon": 36.9308, "method": "nominatim"},
    }

    def lookup(self, name):
        return self.places.get(name.lower())


class ZeroHazard:
    def scores(self, asset):
        return {
            t: 0.0 for t in ("extreme", "severe", "moderate", "occasional", "common")
        }


TEXT = "\n".join(DOC_LINES)


def prop(**kw):
    base = {
        "name": "Landmark Plaza",
        "address": "Upper Hill, Nairobi",
        "address_quote": "Address: Upper Hill, Nairobi",
        "locality": "Upper Hill",
        "coordinates_text": "-1.2847°S, 36.8247°E",
        "coordinates_quote": "GPS COORDINATES: -1.2847°S, 36.8247°E",
        "construction_text": "RCC Frame",
        "housing_class": "concrete_rcc",
        "construction_quote": "CONSTRUCTION CLASSIFICATION: RCC Frame",
        "floors_above_ground": 18,
        "basement_levels": 2,
        "floors_quote": "Total Number of Floors: 18 (above ground) + 2 (basement)",
        "gross_floor_area_m2": 24500,
        "gross_floor_area_quote": "GROSS FLOOR AREA: 24,500 m2",
        "floor_area_components": [
            {"label": "Typical", "area_m2": 1280, "count": 16},
            {"label": "Ground", "area_m2": 2150, "count": 1},
        ],
        "tiv_kes": 1.09e9,
        "tiv_quote": "full TIV (KES 1,090,000,000)",
        "tiv_context": "full TIV",
        "flood_deductible": {"percent": 5, "percent_of": "unclear", "minimum_kes": 5e6},
        "flood_deductible_quote": "5% deductible or KES 5,000,000 minimum",
        "flood_limit_kes": 1.09e9,
        "flood_limit_quote": "full TIV (KES 1,090,000,000)",
        "basement_uses": ["generators", "transformers"],
        "flood_claims": [
            {
                "claim": "No flood losses",
                "quote": "No flood losses recorded in 11 years",
            }
        ],
        "landmarks": [
            {
                "name": "Kenyatta University",
                "direction": "East",
                "distance_km": 3.2,
                "quote": "Kenyatta University (East) - 3.2 km",
            },
            {
                "name": "Nairobi River",
                "direction": "South",
                "distance_km": 1.2,
                "quote": "",
            },
        ],
        "loss_history_years": 11,
        "flood_losses_reported": False,
        "loss_history_quote": "No flood losses recorded in 11 years",
    }
    return {**base, **kw}


DEFAULTS = {"concrete_rcc": {"floor_area_m2": 768.0, "cost_per_m2_kes": 70500.0}}


def assess(config, **kw):
    return build_submission(
        TEXT,
        {"properties": [prop(**kw)]},
        FakeGaz(),
        ZeroHazard(),
        (),
        config,
        DEFAULTS,
        "fake",
    )["properties"][0]


def codes(p):
    return {c["code"] for c in p["checks"]}


def test_landmark_plaza_style_checks(config):
    p = assess(config)
    assert {
        "location_conflict",
        "low_value",
        "deductible_basis",
        "basements",
        "proxy_blind",
        "landmarks",
        "short_history",
    } <= codes(p)
    assert p["deductible_suggestion"] == "loss"
    assert all(f["verified"] in (True, None) for f in p["fields"].values())
    assert next(l for l in p["landmarks"] if l["name"] == "Nairobi River")[
        "status"
    ].startswith("not checked")


def test_area_mismatch_flagged(config):
    p = assess(
        config,
        floor_area_components=[
            {"label": "Typical", "area_m2": 1280, "count": 16},
            {"label": "Ground", "area_m2": 2150, "count": 1},
            {"label": "Basement", "area_m2": 2100, "count": 2},
            {"label": "Mezzanine", "area_m2": 1850, "count": 1},
        ],
    )
    assert "area_mismatch" in codes(p)


def test_hallucinated_values_are_flagged(config):
    p = assess(config, tiv_kes=2e9, tiv_quote="KES 2,000,000,000 insured")
    assert (
        "unverified_field" in codes(p) and p["fields"]["tiv_kes"]["verified"] is False
    )


def test_missing_class_value_and_location_are_errors(config):
    p = assess(
        config,
        housing_class="unknown",
        tiv_kes=None,
        tiv_quote="",
        coordinates_text=None,
        locality="",
    )
    assert {"no_class", "no_tiv", "no_location"} <= {
        c["code"] for c in p["checks"] if c["severity"] == "error"
    }


def test_rows_pass_the_csv_contract_after_declaration(config):
    p = assess(config)
    r = to_exposure_row(p, p["hazard"][0], "OFFER.pdf", "fake")
    assert r["synthetic"] == ""  # the user must declare test data
    assets, issues = validate_rows([{**r, "synthetic": "True"}])
    assert len(assets) == 1 and not [i for i in issues if i["severity"] == "error"]
    a = assets[0]
    assert (
        a.floors_above_ground == 18
        and a.basement_levels == 2
        and a.deductible_pct_of_loss == 0.05
        and a.deductible_kes == Decimal("5000000.00")
    )
    by_value = to_exposure_row(
        p, p["hazard"][0], "OFFER.pdf", "fake", deductible_basis="value"
    )
    assert (
        by_value["deductible_kes"] == "54500000.00"
        and "deductible_pct_of_loss" not in by_value
    )


def test_abusive_responses_rejected(config):
    for response in (None, {}, {"properties": []}, {"properties": [prop()] * 51}):
        with pytest.raises(ModelError):
            build_submission(
                TEXT, response, FakeGaz(), ZeroHazard(), (), config, DEFAULTS
            )


def test_exposed_fraction_for_tall_buildings(config):
    tower, _ = validate_rows([row(floors_above_ground="18", basement_levels="2")])
    house, _ = validate_rows([row()])
    assert (
        exposed_fraction(tower[0], config) == pytest.approx(3 / 20)
        and exposed_fraction(house[0], config) == 1.0
    )
    off = config.replace(
        storey_exposure={"enabled": False, "flooded_storeys_above_ground": 1}
    )
    assert exposed_fraction(tower[0], off) == 1.0


def test_tower_loss_scales_with_exposed_share(config):
    flat = analyse([row(tiv="1000000", scores=(0, 0, 0, 0, 2 / 3))], config)["runs"][
        "baseline"
    ]["property_losses"]["common"][0]
    tall = analyse(
        [
            row(
                tiv="1000000",
                scores=(0, 0, 0, 0, 2 / 3),
                floors_above_ground="9",
                basement_levels="1",
            )
        ],
        config,
    )["runs"]["baseline"]["property_losses"]["common"][0]
    assert Decimal(tall["loss_kes"]) == (
        Decimal(flat["loss_kes"]) * Decimal("0.2")
    ).quantize(Decimal("0.01"))


def test_percent_of_loss_deductible_with_minimum(config):
    terms = config.replace(
        policy_terms={
            "enabled": True,
            "deductible_pct_of_tiv": 0.0,
            "limit_pct_of_tiv": 1.0,
        }
    )
    # gross 380,000: 5% = 19,000 < minimum 50,000 → insured 330,000; with a 10k minimum → 361,000.
    base = dict(tiv="1000000", scores=(0, 0, 0, 0, 2 / 3), deductible_pct_of_loss="5%")
    a = analyse([row(**base, deductible_kes="50000")], terms)["runs"]["baseline"][
        "property_losses"
    ]["common"][0]
    b = analyse([row(**base, deductible_kes="10000")], terms)["runs"]["baseline"][
        "property_losses"
    ]["common"][0]
    assert a["insured_loss_kes"] == "330000.00" and b["insured_loss_kes"] == "361000.00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("floors_above_ground", "2.5"),
        ("floors_above_ground", "0"),
        ("basement_levels", "-1"),
        ("deductible_pct_of_loss", "150%"),
    ],
)
def test_bad_new_fields_rejected(field, value):
    _, issues = validate_rows([row(**{field: value})])
    assert any(i["severity"] == "error" for i in issues)


from floodcat.ai.privacy import redact
from floodcat.exposure.loaders import classify_upload, parse_xlsx


def test_redaction_removes_contacts_but_keeps_figures():
    text = (
        "Contact: +254 (20) 555-0147 | jmwangi@eastside-brokers.co.ke, call 0722 123 456. "
        "GPS -1.2847°S, 36.8247°E; TIV KES 1,090,000,000; GFA 24,500 m²; permit #NAI-CBD-2014-1247; 2015-2026; 1,612 m"
    )
    clean, counts = redact(text)
    assert (
        counts == {"emails": 1, "phones": 2}
        and "@" not in clean
        and "555-0147" not in clean
        and "0722" not in clean
    )
    for figure in (
        "-1.2847",
        "1,090,000,000",
        "24,500",
        "NAI-CBD-2014-1247",
        "2015-2026",
        "1,612",
    ):
        assert figure in clean


def test_documents_are_redacted_when_read():
    doc = read_document(
        make_docx(
            ["Broker: j.doe@example.co.ke, +254 722 123 456", "TIV KES 5,000,000"]
        ),
        "memo.docx",
    )
    assert (
        "@" not in doc["text"]
        and doc["redacted"] == {"emails": 1, "phones": 1}
        and "5,000,000" in doc["text"]
    )


def make_xlsx(rows):
    S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    strings, body = [], ""
    for r, values in enumerate(rows, 1):
        cells = ""
        for c, v in enumerate(values):
            ref = chr(65 + c) + str(r)
            if isinstance(v, str):
                strings.append(v)
                cells += f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
            else:
                cells += f'<c r="{ref}"><v>{v}</v></c>'
        body += f'<row r="{r}">{cells}</row>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{S}">'
            + "".join(f"<si><t>{s}</t></si>" for s in strings)
            + "</sst>",
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{S}"><sheetData>{body}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def test_excel_schedule_reads_into_the_contract():
    data = make_xlsx(
        [
            [
                "Property ID",
                "Latitude",
                "Longitude",
                "Construction",
                "TIV",
                "Floors above ground",
            ],
            ["A1", -1.2576, 36.8962, "concrete", 3300000, 4],
        ]
    )
    assert classify_upload(data, "schedule.xlsx") == "xlsx"
    rows = parse_xlsx(data)
    assets, issues = validate_rows(
        [{**r, "synthetic": "False", "source": "schedule"} for r in rows]
    )
    assert (
        len(assets) == 1
        and assets[0].housing_class == "concrete_rcc"
        and assets[0].floors_above_ground == 4
    )


@pytest.mark.parametrize(
    "data,kind",
    [
        (b"loc_id,lat,lon,housing_class,tiv_kes\nA,-1.28,36.82,concrete,1\n", "table"),
        (b"Dear Underwriter, please find the placement details...", "document"),
        (b"%PDF-1.4\n", "document"),
    ],
)
def test_upload_routing(data, kind):
    assert classify_upload(data) == kind


def test_docx_routes_to_document():
    assert classify_upload(make_docx(["memo"])) == "document"
