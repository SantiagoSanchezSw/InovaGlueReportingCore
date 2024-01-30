# Models
from inova_core.models import Cliente, Fiscalizacion
from reporting_core.models import CustomReport
# Glue reporting core
from .formats.visit import HTMLReport, ExcelReport, CombinedReport, DefaultReport
# Types
from reporting_core.types import GeneratedReport, QuerySet
# Enums
from reporting_core.enums import CustomReportType

#create a new builder

class ReportBuilder:
    client: Cliente
    visit: Fiscalizacion

    def __init__(self, client: Cliente, visit: Fiscalizacion) -> None:
        self.client = client
        self.visit = visit

    def generate_default(self) -> GeneratedReport:
        types = CustomReport.objects.filter(
            client_id=self.client.pk,
            rule_id=self.visit.norma_id,
            default=True
        )
        if types.exists():
            custom_report = types.first()
            generated = self.__get_custom_report(custom_report)
        else:
            generated = DefaultReport(self.visit, self.client).generate()
        return generated

    def generate_by_type(self, custom_report: QuerySet[CustomReport]) -> GeneratedReport:
        if custom_report.exists():
            custom_report = custom_report.first()
            generated = self.__get_custom_report(custom_report)
        else:
            generated = DefaultReport(self.visit, self.client).generate()
        return generated

    def __get_custom_report(self, custom_report: CustomReport) -> GeneratedReport:
        if custom_report.type == CustomReportType.HTML.value:
            generated = HTMLReport(
                template=custom_report, client=self.client, visit=self.visit
            ).generate()
        elif custom_report.type == CustomReportType.EXCEL.value:
            generated = ExcelReport(
                template=custom_report, client=self.client, visit=self.visit
            ).generate()
        elif custom_report.type == CustomReportType.COMBINED.value:
            generated = CombinedReport(
                template=custom_report, client=self.client, visit=self.visit
            ).generate()
        else:
            generated = DefaultReport(self.visit, self.client).generate()
        return generated