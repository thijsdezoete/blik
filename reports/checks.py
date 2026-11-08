from django.core.checks import Error, Tags, register


@register(Tags.compatibility, deploy=False)
def pdf_engine_check(app_configs, **kwargs):
    # Fail at startup, not at the first report, when the system libraries are missing.
    try:
        import weasyprint

        pdf = weasyprint.HTML(string='<p>ok</p>').write_pdf()
        if not pdf.startswith(b'%PDF'):
            raise ValueError('output is not a PDF')
    except Exception as exc:
        return [Error(
            f'WeasyPrint cannot build a PDF: {exc}',
            hint='Install the Pango and HarfBuzz system libraries.',
            id='reports.E001',
        )]
    return []
