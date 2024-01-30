from django.conf import settings
from django.template.loader import render_to_string
from weasyprint import HTML, CSS
from weasyprint.fonts import FontConfiguration
import uuid
# Classes
from reporting_core.classes import InOvaReport
# Models
from inova_core.models import Evento, Cliente
# Helpers
from inova_core.helpers.user import get_client_by_professional, get_client_language
# Types
from reporting_core.types import GeneratedReport
from typing import Dict, Any
import requests
from django.template import Context, Template


class DefaultEventReport(InOvaReport):
    event: Evento
    client: Cliente
    language: Dict[str, str]
    USE_GLUE: bool = True

    def __init__(self, event: Evento):
        self.event = event
        self.client = get_client_by_professional(event.profesional, using=settings.REPORTING_CORE_DB)
        self.language = get_client_language(self.client, using=settings.REPORTING_CORE_DB)

    def generate(self) -> GeneratedReport:
        context = self.build_context()
        if self.USE_GLUE:
            html_content = requests.get('https://aws-base.s3.amazonaws.com/templates/detail.html').text
            template = Template(html_content)
            html_template = template.render(context)
        else:
            html_template = render_to_string('detail_event.html', context)
        css = CSS(string='@media print { .new-page { page-break-before: always; } } )', font_config=FontConfiguration())
        file_name = '{}.pdf'.format(uuid.uuid4())
        file_path = settings.TEMPORAL_DIR + file_name
        HTML(
            string=html_template,
            base_url=settings.DOMAIN
        ).write_pdf(
            target=file_path,
            presentational_hints=True,
            stylesheets=[css]
        )
        return GeneratedReport(path=file_path, file_name=file_name)

    def build_context(self) -> Dict[str, Any]:
        context = Context({
            'object': self.event,
            'profesional': self.get_person_name(self.event.profesional.usuario.persona),
            'cliente': self.client,
            'footer': self.client.temp_reporte_footer if self.client.reporte_footer else '',
            'header': self.client.temp_reporte_header if self.client.reporte_header else '',
        })
        return context
