from django.conf import settings
from PyPDF2 import PdfMerger
from django.core.exceptions import ObjectDoesNotExist
from graphql_relay import from_global_id
import uuid
import os
# Models
from inova_core.models import Cliente, Fiscalizacion
from reporting_core.models import CustomReport
# Classes
from reporting_core.classes.inova_report import InOvaReport
from .excel_report import ExcelReport
from .default_report import DefaultReport
from .html_report import HTMLReport
# Helpers
from reporting_core.helpers.file import remove_generated_file
from inova_base.helpers.boto3_helper import generate_s3_temp_url
# Types
from typing import Optional, List
from reporting_core.types import GeneratedReport
# Enums
from reporting_core.enums import CustomReportType, Extension
import sys


class CombinedReport(InOvaReport):
    visit: Fiscalizacion
    template: CustomReport
    preview: bool = False
    client: Cliente
    generated_files: List[str]
    file_id: uuid.UUID

    def __init__(self, template: CustomReport, client: Cliente, visit: Optional[Fiscalizacion] = None) -> None:
        if visit:
            self.visit = visit
        else:
            self.preview = True
            self.visit = Fiscalizacion.objects.using(settings.REPORTING_CORE_DB).filter(
                norma__pk=template.rule_id
            ).select_related(
                'entidad', 'entidad__productor', 'entidad__productor__persona', 'profesional',
                'profesional__usuario', 'profesional__usuario__persona'
            ).last()
        self.client = client
        self.template = template
        self.generated_files = []

    def generate(self) -> GeneratedReport:
        self.file_id = uuid.uuid4()
        for global_id in self.template.order:
            custom_report = self.get_custom_report_or_none(global_id)
            if custom_report:
                if custom_report.type == CustomReportType.HTML.value:
                    self.generated_files.append(
                        HTMLReport(custom_report, self.client, self.visit).generate()['path']
                    )
                elif custom_report.type == CustomReportType.EXCEL.value:
                    self.generated_files.append(
                        ExcelReport(custom_report, self.client, self.visit).generate()['path']
                    )
                elif custom_report.type == CustomReportType.INOVA.value:
                    self.generated_files.append(
                        DefaultReport(self.visit, self.client).generate()['path']
                    )
        if self.template.append_annexes:
            self.append_annexes()
        report = self.merge_files()
        self.remove_generated_files()
        return GeneratedReport(
            path=report,
            file_name='joined_{}.pdf'.format(self.file_id),
            custom_report=self.template
        )



    def append_annexes(self) -> None:
        visible_annexes = list(filter(lambda i: i['visible_en_pdf'], self.visit.anexos or []))
        for annex in visible_annexes:
            files = list(filter(lambda i: i.split('.').pop().lower() == Extension.PDF, annex['archivos']))
            for file_url in files:
                downloaded_path = self.download_file_to_tmp_folder(
                    file_url=generate_s3_temp_url(file_url),
                    file_name=str(uuid.uuid4()),
                    extension=Extension.PDF
                )
                if self.is_valid_pdf(downloaded_path):
                    self.generated_files.append(downloaded_path)
                else:
                    os.remove(downloaded_path)
        return None

    def merge_files(self) -> str:
        print("entra al merge files ESTA VISITA", self.visit.pk,  self.generated_files)
        merger = PdfMerger()
        for file_path in self.generated_files:
            try:
                merger.append(file_path)
            except:
                # Corrupt file
                pass
        joined_path = '{}joined_{}.pdf'.format(settings.TEMPORAL_DIR, self.file_id)
        merger.write(joined_path)
        merger.close()
        return joined_path

    def remove_generated_files(self) -> None:
        for path in self.generated_files:
            remove_generated_file(path)
        return None

    @staticmethod
    def get_custom_report_or_none(global_id: str) -> Optional[CustomReport]:
        try:
            return CustomReport.objects.get(pk=from_global_id(global_id)[1])
        except ObjectDoesNotExist:
            return None
