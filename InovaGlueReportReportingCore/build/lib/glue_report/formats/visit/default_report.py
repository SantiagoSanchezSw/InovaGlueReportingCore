from django.conf import settings
from django.template.loader import get_template
from weasyprint import HTML, CSS
from weasyprint.fonts import FontConfiguration
from unidecode import unidecode
import re
# Models
from inova_core.models import Fiscalizacion, Cliente, ConfiguracionReporte, Pregunta
# Classes
from reporting_core.classes.inova_report import InOvaReport
# Types
from typing import Dict, Optional, List, Any
from reporting_core.types import GeneratedReport
# Helpers
from inova_base.helpers.user.client import get_client_language
# Constants
from inova_core.constants.question import question_type
import os


REPORTING_CORE_MAIN_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'templates',
)


class DefaultReport(InOvaReport):
    visit: Fiscalizacion
    client: Cliente
    language: Dict[str, str]
    USE_GLUE: bool = True

    def __init__(self, visit: Fiscalizacion, client: Cliente, language: Optional[Dict[str, str]] = None) -> None:
        self.visit = visit
        self.client = client
        self.language = language if language else get_client_language(self.client, using=settings.REPORTING_CORE_DB)

    def generate(self) -> GeneratedReport:
        context = self.build_context()
        file_name = self.format_file_name()
        html_template = get_template('detail.html').render(context)
        path = settings.TEMPORAL_DIR + file_name
        font_config = FontConfiguration()
        css = CSS(
            string='@media print { .new-page { page-break-before: always; } }',
            font_config=font_config
        )
        HTML(
            string=html_template,
            base_url=settings.DOMAIN
        ).write_pdf(
            target=path,
            presentational_hints=True,
            stylesheets=[css],
            font_config=font_config
        )
        return GeneratedReport(
            path=path,
            file_name=file_name,
            custom_report=None
        )

    def build_context(self) -> Dict[str, Any]:

        regular_form = self.visit.profesional_id and self.visit.entidad_id
        qs = ConfiguracionReporte.objects.using(settings.REPORTING_CORE_DB).filter(
            norma_id=self.visit.norma_id, cliente=self.client
        )
        report_config = qs.first() if qs.exists() else None
        return {
            'object': self.visit,
            'professional': self.get_person_name(self.visit.profesional.usuario.persona) if regular_form else None,
            'lenguaje': self.language,
            'tipo': question_type,
            'cliente': self.client,
            'footer': report_config.temp_footer if report_config and report_config.footer else '',
            'header': report_config.temp_header if report_config and report_config.header else '',
            'visibles_norma': self.get_visible_rule_questions(),
            'visibles_norma_cliente': self.get_visible_client_questions() if regular_form else None,
            'anexos': self.build_annexes(),
            'firmas': self.build_signatures(),
            'plan_de_trabajo': self.build_work_plan(),
            'calificacion': self.build_calification(),
            'capitulos': self.build_chapters(),
            'idiom': self.get_client_idiom_keys(),
            'location_values': self.build_location_values(),
            'capitulos_visibles': self.get_visible_rule_chapters(),
        }

    def get_visible_client_questions(self) -> Optional[List[int]]:
        if self.client.norma_informacion:
            return Pregunta.objects.using(settings.REPORTING_CORE_DB).filter(
                capitulo__norma__pk=self.client.norma_informacion.pk,
                opciones__visible_pdf=True
            ).values_list('pk', flat=True)
        return None

    def format_file_name(self):
        if self.visit.entidad_id and self.visit.profesional_id:
            producer_name = self.get_person_name(self.visit.entidad.productor.persona)
            formated_name = unidecode(producer_name).lower().strip()
            formated_name = formated_name.replace(' ', '_').replace('n/a', '').replace('pendiente', '')
            formated_name = re.sub('[^A-Za-z0-9]+', '', formated_name)
            if self.visit.entidad.productor.persona.cedula.find('$') < 0:
                identification = self.visit.entidad.productor.persona.cedula
            else:
                identification = ''
            identification = re.sub('[^A-Za-z0-9]+', '', identification)
            return '{0}_{1}_{2}.pdf'.format(identification, formated_name, self.visit.pk).replace('/', '')
        else:
            formated_name = unidecode(self.visit.norma.descripcion).lower().strip().replace(' ', '_')
            formated_name = formated_name.replace('/', '')
            return '{}_{}.pdf'.format(formated_name, str(self.visit.pk))
