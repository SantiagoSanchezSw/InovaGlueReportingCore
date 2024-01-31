from django.conf import settings
from unidecode import unidecode
import re
# Models
from inova_core.models import Fiscalizacion, Cliente
# Classes
from reporting_core.classes.inova_report import InOvaReport
# Types
from typing import Dict, Optional
from reporting_core.types import GeneratedReport
# Helpers
from inova_base.helpers.user.client import get_client_language
# Constants
import os
# helpers
from glue_report.helpers.external_report import build_report_in_lambda


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
        report = build_report_in_lambda(self.visit, self.client, None)
        file_name = self.format_file_name()
        return GeneratedReport(
            path=report,
            file_name=file_name
        )


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
