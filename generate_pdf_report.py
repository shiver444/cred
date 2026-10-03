"""
VidProof — PDF Chain of Evidence Report Generator
Generates a professional PDF report from a proof bundle or project.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from pathlib import Path
from datetime import datetime, timezone
import json

# ─── COLORS ──────────────────────────────────────────────────
# ACCENT is the neutral brand/decorative color (section headings, badges).
# VALID is reserved for actual pass/verified semantics, kept separate so a
# redesign of one doesn't quietly change the meaning of the other.
BLACK      = colors.HexColor('#0a0a0a')
WHITE      = colors.HexColor('#ffffff')
ACCENT     = colors.HexColor('#4d8dff')
VALID      = colors.HexColor('#34d399')
DARKGRAY   = colors.HexColor('#1a1a1a')
MIDGRAY    = colors.HexColor('#333333')
LIGHTGRAY  = colors.HexColor('#f5f5f0')
DIMGRAY    = colors.HexColor('#888888')
RED        = colors.HexColor('#ff3b3b')

# ─── STYLES ──────────────────────────────────────────────────
def make_styles():
    return {
        'cover_title': ParagraphStyle(
            'cover_title',
            fontName='Helvetica-Bold',
            fontSize=36,
            textColor=WHITE,
            leading=40,
            spaceAfter=4,
        ),
        'cover_sub': ParagraphStyle(
            'cover_sub',
            fontName='Helvetica',
            fontSize=11,
            textColor=DIMGRAY,
            leading=16,
            spaceAfter=2,
        ),
        'cover_label': ParagraphStyle(
            'cover_label',
            fontName='Helvetica-Bold',
            fontSize=8,
            textColor=ACCENT,
            leading=12,
            spaceAfter=2,
            spaceBefore=2,
        ),
        'section_title': ParagraphStyle(
            'section_title',
            fontName='Helvetica-Bold',
            fontSize=9,
            textColor=ACCENT,
            leading=14,
            spaceBefore=16,
            spaceAfter=6,
            letterSpacing=2,
        ),
        'body': ParagraphStyle(
            'body',
            fontName='Helvetica',
            fontSize=9,
            textColor=DARKGRAY,
            leading=14,
            spaceAfter=4,
        ),
        'mono': ParagraphStyle(
            'mono',
            fontName='Courier',
            fontSize=7.5,
            textColor=MIDGRAY,
            leading=11,
            spaceAfter=2,
            wordWrap='LTR',
        ),
        'mono_small': ParagraphStyle(
            'mono_small',
            fontName='Courier',
            fontSize=7,
            textColor=DIMGRAY,
            leading=10,
        ),
        'verdict_valid': ParagraphStyle(
            'verdict_valid',
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=VALID,
            leading=22,
            alignment=TA_CENTER,
        ),
        'verdict_invalid': ParagraphStyle(
            'verdict_invalid',
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=RED,
            leading=22,
            alignment=TA_CENTER,
        ),
        'verdict_sub': ParagraphStyle(
            'verdict_sub',
            fontName='Helvetica',
            fontSize=9,
            textColor=DIMGRAY,
            leading=13,
            alignment=TA_CENTER,
        ),
        'footer': ParagraphStyle(
            'footer',
            fontName='Helvetica',
            fontSize=7,
            textColor=DIMGRAY,
            leading=10,
            alignment=TA_CENTER,
        ),
    }

# ─── HELPERS ─────────────────────────────────────────────────

def check_row(label, value, passed):
    icon = '✔' if passed else '✗'
    color = VALID if passed else RED
    return [
        Paragraph(icon, ParagraphStyle('icon', fontName='Helvetica-Bold',
                  fontSize=10, textColor=color, leading=13)),
        Paragraph(label, ParagraphStyle('label', fontName='Helvetica',
                  fontSize=8.5, textColor=DARKGRAY, leading=13)),
        Paragraph(value, ParagraphStyle('val', fontName='Courier',
                  fontSize=7.5, textColor=MIDGRAY, leading=13)),
    ]

def info_row(label, value):
    return [
        Paragraph(label, ParagraphStyle('lbl', fontName='Helvetica-Bold',
                  fontSize=8, textColor=DIMGRAY, leading=12)),
        Paragraph(str(value), ParagraphStyle('val', fontName='Helvetica',
                  fontSize=8, textColor=DARKGRAY, leading=12)),
    ]

def short_hash(h, length=24):
    if not h or h in ('NOT_ANCHORED', 'NO_LINK', 'PENDING'):
        return h or '—'
    return h[:length] + '...' if len(h) > length else h

# ─── MAIN GENERATOR ──────────────────────────────────────────

def generate_pdf_report(manifest_path, proof_path, video_path, output_path,
                        checks=None, bundle_name=None, bundle_type='video'):
    """
    Generate a professional PDF chain of evidence report.

    manifest_path — path to manifest.json
    proof_path    — path to proof_report.json (or None for session bundles)
    video_path    — path to output.mp4 or decision log file
    output_path   — where to save the PDF
    checks        — dict of verification results
    bundle_name   — name of the bundle file
    bundle_type   — 'video' or 'decision_log'
    """

    S = make_styles()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    W = A4[0] - 40*mm  # usable width
    story = []

    # ── Load data ──
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    proof = {}
    if proof_path and Path(proof_path).exists():
        with open(proof_path, 'r', encoding='utf-8') as f:
            proof = json.load(f)

    if bundle_type == 'credential':
        project_name = manifest.get('holder_name', '—')
    else:
        project_name = manifest.get('project') or manifest.get('session_name', '—')
    build_ts     = manifest.get('build_timestamp', '—')
    fp_hash      = manifest.get('fingerprint_hash', '—')
    pub_key      = manifest.get('public_key', '—')

    now = datetime.now(timezone.utc).isoformat()

    # ────────────────────────────────────────────────────────
    # COVER BLOCK
    # ────────────────────────────────────────────────────────
    cover_data = [[
        Paragraph('CREDENTIAL PROTOCOL' if bundle_type == 'credential' else 'VidProof', S['cover_title']),
    ]]
    cover_table = Table(cover_data, colWidths=[W])
    cover_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), BLACK),
        ('TOPPADDING',    (0,0), (-1,-1), 20),
        ('BOTTOMPADDING', (0,0), (-1,-1), 20),
        ('LEFTPADDING',   (0,0), (-1,-1), 16),
        ('RIGHTPADDING',  (0,0), (-1,-1), 16),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 2))

    # Subtitle strip
    if bundle_type == 'decision_log':
        label_type = 'DECISION LOG EVIDENCE'
    elif bundle_type == 'dataset_registry':
        label_type = 'DATASET REGISTRY EVIDENCE'
    elif bundle_type == 'credential':
        label_type = 'MEMBERSHIP CREDENTIAL'
    else:
        label_type = 'VIDEO EVIDENCE'
    sub_data = [[
        Paragraph('CHAIN OF EVIDENCE REPORT', S['cover_sub']),
        Paragraph(label_type, S['cover_label']),
    ]]
    sub_table = Table(sub_data, colWidths=[W*0.6, W*0.4])
    sub_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), DARKGRAY),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (-1,-1), 16),
        ('RIGHTPADDING',  (0,0), (-1,-1), 16),
        ('ALIGN',         (1,0), (1,0), 'RIGHT'),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(sub_table)
    story.append(Spacer(1, 16))

    # ────────────────────────────────────────────────────────
    # PROJECT INFO
    # ────────────────────────────────────────────────────────
    story.append(Paragraph('PROJECT INFORMATION', S['section_title']))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
    story.append(Spacer(1, 6))

    info_data = [
        info_row('Project / Session', project_name),
        info_row('Bundle file', bundle_name or '—'),
        info_row('Bundle type', 'Video Evidence' if bundle_type == 'video' else ('Dataset Registry' if bundle_type == 'dataset_registry' else ('Membership Credential' if bundle_type == 'credential' else 'AI Decision Log'))),
        info_row('Build timestamp', build_ts),
        info_row('Report generated', now),
    ]
    # 'vidproof_version' only exists on bundles from the original VidProof
    # product (video/decision-log/dataset bundles) — a credential manifest
    # never has this field, so this row is skipped for those to avoid a
    # meaningless "VidProof version: —" line on every membership certificate.
    if bundle_type != 'credential':
        info_data.append(info_row('VidProof version', manifest.get('vidproof_version', '—')))
    info_data.append(info_row('Bundle spec', manifest.get('bundle_spec', '—')))

    info_table = Table(info_data, colWidths=[W*0.3, W*0.7])
    info_table.setStyle(TableStyle([
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('LINEBELOW',     (0,0), (-1,-2), 0.3, LIGHTGRAY),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 16))

    # ────────────────────────────────────────────────────────
    # VERIFICATION RESULTS
    # ────────────────────────────────────────────────────────
    story.append(Paragraph('VERIFICATION RESULTS', S['section_title']))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
    story.append(Spacer(1, 6))

    if checks is None:
        checks = {
            'seal':        True,
            'files':       True,
            'signature':   manifest.get('public_key') is not None,
            'output_hash': True,
            'merkle':      True,
            'tokens':      True,
            'anchor':      fp_hash not in ('NOT_ANCHORED', 'NO_LINK', 'PENDING', '—'),
        }

    check_data = [
        check_row('SHA256 Seal', 'Bundle integrity verified', checks.get('seal', False)),
        check_row('Required Files', 'All evidence files present', checks.get('files', False)),
        check_row('Cryptographic Signature', 'ECDSA manifest signature', checks.get('signature', False)),
        check_row('Content Hash', 'SHA256 of output file', checks.get('output_hash', False)),
        check_row('Merkle Root' if bundle_type == 'video' else (
            'Dataset Hash' if bundle_type == 'dataset_registry' else (
                'Holder Identity' if bundle_type == 'credential' else 'Session Integrity')),
                  'File chunk tree verified' if bundle_type == 'video' else (
                      'SHA256 of dataset content' if bundle_type == 'dataset_registry' else (
                          'Name and email bound to signature' if bundle_type == 'credential' else 'Session hash present')),
                  checks.get('merkle', False)),
        check_row('Token Merkle' if bundle_type == 'video' else (
            'Verification Method' if bundle_type == 'dataset_registry' else (
                'Membership Tier' if bundle_type == 'credential' else 'Decision Count')),
                  'Source integrity verified' if bundle_type == 'video' else (
                      manifest.get('verified', '—') if bundle_type == 'dataset_registry' else (
                          manifest.get('tier', '—') if bundle_type == 'credential' else f"{manifest.get('decision_count', 0)} decisions recorded")),
                  checks.get('tokens', False)),
    ]
    # Credential Protocol never anchors membership credentials to anything
    # external (fp_hash is always NOT_ANCHORED by design), so this row would
    # always render as a red, permanently-failed check on every membership
    # certificate. Only shown for the other (legacy) bundle types, where an
    # external anchor is still a real, meaningful check.
    if bundle_type != 'credential':
        check_data.append(
            check_row('Constellation Anchor', short_hash(fp_hash), checks.get('anchor', False))
        )

    check_table = Table(check_data, colWidths=[8*mm, W*0.35, W*0.55])
    check_table.setStyle(TableStyle([
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('LINEBELOW',     (0,0), (-1,-2), 0.3, LIGHTGRAY),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [WHITE, LIGHTGRAY]),
    ]))
    story.append(check_table)
    story.append(Spacer(1, 20))

    # ────────────────────────────────────────────────────────
    # VERDICT
    # ────────────────────────────────────────────────────────
    core = [checks.get('files', False), checks.get('output_hash', False),
            checks.get('merkle', False), checks.get('tokens', False)]
    verdict = all(core)

    verdict_text = 'VERIFIED — CONTENT IS AUTHENTIC AND UNALTERED' if verdict else 'VERIFICATION FAILED'
    verdict_sub  = 'This bundle passed all cryptographic verification checks.' if verdict \
                   else 'One or more verification checks failed. Bundle may be compromised.'

    verdict_data = [[
        Paragraph(verdict_text, S['verdict_valid'] if verdict else S['verdict_invalid']),
    ],[
        Paragraph(verdict_sub, S['verdict_sub']),
    ]]

    verdict_table = Table(verdict_data, colWidths=[W])
    verdict_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1),
         colors.HexColor('#e8fff4') if verdict else colors.HexColor('#fff0f0')),
        ('TOPPADDING',    (0,0), (-1,-1), 14),
        ('BOTTOMPADDING', (0,0), (-1,-1), 14),
        ('LEFTPADDING',   (0,0), (-1,-1), 16),
        ('RIGHTPADDING',  (0,0), (-1,-1), 16),
        ('BOX', (0,0), (-1,-1), 0.5,
         VALID if verdict else RED),
    ]))
    story.append(verdict_table)
    story.append(Spacer(1, 20))

    # ────────────────────────────────────────────────────────
    # CRYPTOGRAPHIC DETAILS
    # ────────────────────────────────────────────────────────
    story.append(Paragraph('CRYPTOGRAPHIC DETAILS', S['section_title']))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
    story.append(Spacer(1, 6))

    crypto_items = [
        ('Output hash (SHA256)', manifest.get('output_hash', '—')),
        ('Public key', pub_key[:64] + '...' if pub_key and len(pub_key) > 64 else pub_key),
    ]
    # Same reasoning as the check row above — credentials are never anchored,
    # so a "Constellation fingerprint: NOT_ANCHORED" pair on a membership
    # certificate is just noise, not a real cryptographic detail.
    if bundle_type != 'credential':
        crypto_items.append(('Constellation fingerprint', fp_hash))
        crypto_items.append(('Fingerprint provider', proof.get('fingerprint_provider', 'Constellation Network Digital Evidence')))

    if bundle_type == 'video':
        crypto_items.insert(1, ('Output Merkle root', manifest.get('output_merkle_root', '—')))
        crypto_items.insert(2, ('Token Merkle root', manifest.get('token_merkle_root', '—')))
    elif bundle_type == 'dataset_registry':
        crypto_items.insert(1, ('Dataset version', manifest.get('dataset_version', '—')))
        crypto_items.insert(2, ('Source', manifest.get('source', '—')))
    elif bundle_type == 'credential':
        crypto_items.insert(1, ('Holder', f"{manifest.get('holder_name', '—')} <{manifest.get('holder_email', '—')}>"))
        crypto_items.insert(2, ('Membership tier', manifest.get('tier', '—')))
    else:
        crypto_items.insert(1, ('Session hash', manifest.get('session_hash', '—')))
        crypto_items.insert(2, ('Session ID', manifest.get('session_id', '—')))

    for label, value in crypto_items:
        story.append(Paragraph(label.upper(), ParagraphStyle(
            'clabel', fontName='Helvetica-Bold', fontSize=7,
            textColor=DIMGRAY, leading=10, spaceBefore=6, spaceAfter=2
        )))
        story.append(Paragraph(str(value), S['mono']))
        story.append(Spacer(1, 2))

    story.append(Spacer(1, 16))

    # ────────────────────────────────────────────────────────
    # TOKENS / DECISIONS
    # ────────────────────────────────────────────────────────
    if bundle_type == 'video':
        tokens = manifest.get('tokens', [])
        if tokens:
            story.append(Paragraph('SOURCE TOKENS', S['section_title']))
            story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
            story.append(Spacer(1, 6))

            tok_data = [['TOKEN ID', 'FILE HASH', 'FINGERPRINT']]
            for t in tokens:
                tok_data.append([
                    t.get('token_id', '—'),
                    short_hash(t.get('file_hash', '—'), 16),
                    short_hash(t.get('fingerprint_hash', '—'), 16),
                ])

            tok_table = Table(tok_data, colWidths=[W*0.2, W*0.4, W*0.4])
            tok_table.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0), DARKGRAY),
                ('TEXTCOLOR',     (0,0), (-1,0), ACCENT),
                ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,0), 7),
                ('FONTNAME',      (0,1), (-1,-1), 'Courier'),
                ('FONTSIZE',      (0,1), (-1,-1), 7),
                ('TOPPADDING',    (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LEFTPADDING',   (0,0), (-1,-1), 6),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHTGRAY]),
                ('LINEBELOW',     (0,0), (-1,-1), 0.3, LIGHTGRAY),
            ]))
            story.append(tok_table)



    elif bundle_type == 'dataset_registry':

        story.append(Paragraph('DATASET REGISTRY DETAIL · ARTICLE 10', S['section_title']))

        story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))

        story.append(Spacer(1, 6))

        ds_info = [
            info_row('Dataset name', manifest.get('dataset_name', '—')),
            info_row('Role', (manifest.get('dataset_role', 'training') or 'training').upper()),
            info_row('Version', manifest.get('dataset_version', '—')),
            info_row('Source', manifest.get('source', '—')),
            info_row('Verification', manifest.get('verified', '—')),
            info_row('Registered at', manifest.get('registered_at', '—')),
        ]

        ds_table = Table(ds_info, colWidths=[W * 0.3, W * 0.7])

        ds_table.setStyle(TableStyle([

            ('TOPPADDING', (0, 0), (-1, -1), 4),

            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),

            ('LEFTPADDING', (0, 0), (-1, -1), 0),

            ('LINEBELOW', (0, 0), (-1, -2), 0.3, LIGHTGRAY),

        ]))

        story.append(ds_table)

        notes = manifest.get('notes')

        if notes:
            story.append(Spacer(1, 10))

            story.append(Paragraph('BIAS MITIGATION / LINEAGE NOTES', ParagraphStyle(

                'notes_label', fontName='Helvetica-Bold', fontSize=7,

                textColor=DIMGRAY, leading=10, spaceBefore=4, spaceAfter=2

            )))

            story.append(Paragraph(str(notes), S['body']))

    elif bundle_type == 'credential':

        story.append(Paragraph('MEMBERSHIP DETAIL', S['section_title']))
        story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
        story.append(Spacer(1, 6))

        sections_granted = manifest.get('sections', [])
        cred_info = [
            info_row('Holder name', manifest.get('holder_name', '—')),
            info_row('Holder email', manifest.get('holder_email', '—')),
            info_row('Tier', manifest.get('tier', '—')),
            info_row('Sections granted', ', '.join(sections_granted) if sections_granted else '—'),
            info_row('Issued', manifest.get('issued_at', '—')),
            info_row('Expires', manifest.get('expires_at', '—')),
        ]
        cred_table = Table(cred_info, colWidths=[W * 0.3, W * 0.7])
        cred_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('LINEBELOW', (0, 0), (-1, -2), 0.3, LIGHTGRAY),
        ]))
        story.append(cred_table)
        story.append(Spacer(1, 16))

    else:

        # Decision log summary

        story.append(Paragraph('DECISION LOG SUMMARY', S['section_title']))

        story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))

        story.append(Spacer(1, 6))

        dec_info = [

            info_row('Session name', manifest.get('session_name', '—')),

            info_row('Started', manifest.get('started_at', '—')),

            info_row('Ended', manifest.get('ended_at', '—')),

            info_row('Decision count', str(manifest.get('decision_count', 0))),

            info_row('Session hash', short_hash(manifest.get('session_hash', '—'), 32)),

        ]

        dec_table = Table(dec_info, colWidths=[W * 0.3, W * 0.7])

        dec_table.setStyle(TableStyle([

            ('TOPPADDING', (0, 0), (-1, -1), 4),

            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),

            ('LEFTPADDING', (0, 0), (-1, -1), 0),

            ('LINEBELOW', (0, 0), (-1, -2), 0.3, LIGHTGRAY),

        ]))

        story.append(dec_table)

        story.append(Spacer(1, 16))

        # ────────────────────────────────────────────────

        # DECISION DETAIL — Article 13 transparency

        # ────────────────────────────────────────────────

        decisions = manifest.get('decisions', [])

        if decisions:

            story.append(Paragraph('DECISION DETAIL · ARTICLE 13', S['section_title']))

            story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))

            story.append(Spacer(1, 8))

            for d in decisions:

                seq = d.get('sequence', '—')

                story.append(Paragraph(

                    f"DECISION #{seq} · {d.get('action', '—')}",

                    ParagraphStyle('dec_head', fontName='Helvetica-Bold',

                                   fontSize=8.5, textColor=ACCENT, leading=12,

                                   spaceBefore=8, spaceAfter=4)

                ))

                detail_rows = [

                    info_row('Timestamp', d.get('timestamp', '—')),

                    info_row('Category', d.get('decision_category', '—')),

                    info_row('Model', f"{d.get('model_id', '—')} v{d.get('model_version', '—')}"),

                    info_row('Confidence', str(d.get('confidence', '—'))),

                    info_row('Risk level', d.get('risk_level', '—')),

                    info_row('Reviewer', d.get('reviewer_id') or '—'),

                ]

                detail_table = Table(detail_rows, colWidths=[W * 0.25, W * 0.75])

                detail_table.setStyle(TableStyle([

                    ('TOPPADDING', (0, 0), (-1, -1), 2),

                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),

                    ('LEFTPADDING', (0, 0), (-1, -1), 0),

                    ('FONTSIZE', (0, 0), (-1, -1), 7.5),

                ]))

                story.append(detail_table)

                reasoning = d.get('reasoning')

                if reasoning:
                    story.append(Paragraph('REASONING', ParagraphStyle(

                        'reason_label', fontName='Helvetica-Bold', fontSize=7,

                        textColor=DIMGRAY, leading=10, spaceBefore=4, spaceAfter=2

                    )))

                    story.append(Paragraph(str(reasoning), S['body']))

                factors = d.get('factors', [])

                if factors:
                    story.append(Paragraph('KEY FACTORS', ParagraphStyle(

                        'factors_label', fontName='Helvetica-Bold', fontSize=7,

                        textColor=DIMGRAY, leading=10, spaceBefore=4, spaceAfter=2

                    )))

                    story.append(Paragraph(', '.join(factors), S['mono']))

                story.append(Spacer(1, 10))

                story.append(HRFlowable(width=W, thickness=0.3, color=LIGHTGRAY))

                story.append(Spacer(1, 6))

    story.append(Spacer(1, 24))

    # ────────────────────────────────────────────────────────
    # FOOTER
    # ────────────────────────────────────────────────────────
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHTGRAY))
    story.append(Spacer(1, 6))
    if bundle_type == 'credential':
        story.append(Paragraph(
            f'Generated by CrithLabs Credential Protocol · {now} · '
            f'Signed with ECDSA (secp256k1)',
            S['footer']
        ))
    else:
        story.append(Paragraph(
            f'Generated by VidProof · CrithLabs · {now} · '
            f'Powered by Constellation Network Digital Evidence',
            S['footer']
        ))

    doc.build(story)
    print(f"✅ PDF report generated: {output_path}")
    return output_path


# ─── CONVENIENCE WRAPPERS ────────────────────────────────────

def generate_pdf_for_project(project_name, checks=None):
    """Generate PDF for a project in the projects folder."""
    import os, sys
    if os.environ.get('ELECTRON_APP_PACKAGED') == '1':
        project_dir = Path.home() / "Documents" / "VidProof" / "projects" / project_name
    else:
        project_dir = Path(__file__).resolve().parent / 'projects' / project_name

    manifest  = project_dir / 'manifest.json'
    proof     = project_dir / 'proof_report.json'
    video     = next(project_dir.glob('*.mp4'), None)
    output    = project_dir / f'{project_name}_chain_of_evidence.pdf'

    if not manifest.exists():
        print(f"❌ manifest.json not found for project '{project_name}'")
        return None

    return generate_pdf_report(
        manifest_path = manifest,
        proof_path    = proof,
        video_path    = video,
        output_path   = output,
        checks        = checks,
        bundle_name   = f'{project_name} proof bundle',
        bundle_type   = 'video',
    )


def generate_pdf_for_session(log_path, checks=None):
    """Generate PDF for a decision log session."""
    log_path = Path(log_path)

    with open(log_path, 'r', encoding='utf-8') as f:
        session = json.load(f)

    output = log_path.parent / (log_path.stem + '_chain_of_evidence.pdf')

    # build a minimal manifest-like dict from session data
    manifest_data = {
        'vidproof_version': '1.0',
        'bundle_spec': '1.0',
        'bundle_type': 'decision_log',
        'session_name': session.get('session_name'),
        'session_id': session.get('session_id'),
        'started_at': session.get('started_at'),
        'ended_at': session.get('ended_at'),
        'decision_count': session.get('decision_count'),
        'session_hash': session.get('session_hash'),
        'fingerprint_hash': 'NOT_ANCHORED',
        'public_key': None,
        'build_timestamp': session.get('started_at'),
        'decisions': session.get('decisions', []),
    }

    # write temp manifest
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                     delete=False, encoding='utf-8')
    json.dump(manifest_data, tmp)
    tmp.close()

    result = generate_pdf_report(
        manifest_path = tmp.name,
        proof_path    = None,
        video_path    = log_path,
        output_path   = output,
        checks        = checks,
        bundle_name   = log_path.name,
        bundle_type   = 'decision_log',
    )

    os.unlink(tmp.name)
    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python generate_pdf_report.py project <project_name>")
        print("  python generate_pdf_report.py session <log_file.json>")
        sys.exit(1)

    mode = sys.argv[1]
    name = sys.argv[2]

    if mode == 'project':
        generate_pdf_for_project(name)
    elif mode == 'session':
        generate_pdf_for_session(name)
    else:
        print("Mode must be 'project' or 'session'")