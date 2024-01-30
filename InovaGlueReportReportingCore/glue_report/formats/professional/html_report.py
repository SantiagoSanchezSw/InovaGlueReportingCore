from weasyprint import HTML
from django.conf import settings
from datetime import timedelta, datetime
from functools import partial
from PyPDF2 import PdfMerger
from unidecode import unidecode
import uuid
import re
import ast
# Models
from inova_core.models import Fiscalizacion, Profesional, Cliente, Entidad
from reporting_core.models import ProfessionalCustomReport
# Classes
from reporting_core.classes import InOvaReport
from reporting_core.classes.professional import ProfessionalHTMLReportCustomBlock
from inova_base.helpers.boto3_helper import generate_s3_temp_url
# Helpers
from reporting_core.helpers.file import remove_generated_file
# Types
from typing import Dict, Union, List, Tuple, Any, Optional
from reporting_core.types import QuerySet, GeneratedReport
# Enums
from reporting_core.enums import Extension


class ProfessionalHTMLReport(InOvaReport, ProfessionalHTMLReportCustomBlock):
    client: Cliente
    preview: bool
    custom_date: datetime
    generated_files: List[str]

    def __init__(self,
                 template: ProfessionalCustomReport,
                 client: Cliente,
                 professional: Profesional = None,
                 entity: Entidad = None,
                 custom_date: datetime = None) -> None:
        self.preview = False
        if professional:
            self.current_professional = professional
            self.current_entity = entity if entity else None
            self.preview = True
        self.template = template
        self.client = client
        self.visits = dict()
        self.custom_date = custom_date
        self.generated_files = []

    def generate(self) -> Union[GeneratedReport, List[GeneratedReport]]:
        if self.preview:
            return self.process_generated_report()
        else:
            generated = list()
            for _id in self.template.professional_ids:
                self.current_professional = Profesional.objects.using(settings.REPORTING_CORE_DB).get(pk=_id)
                if self.template.split_report_by_entities:
                    for entity in self.current_professional.entidades.all():
                        self.current_entity = entity
                        generated_report = self.process_generated_report()
                        if generated_report:
                            generated.append(generated_report)
                else:
                    generated_report = self.process_generated_report()
                    if generated_report:
                        generated.append(generated_report)
            return generated

    def process_generated_report(self) -> Optional[GeneratedReport]:
        generated = None
        self.set_current_professional_visits(self.current_entity.id if self.current_entity else None)
        if self.professional_has_visits():
            html, file_name = self.build_html_template_and_file_name(
                self.current_entity.nombre if self.current_entity else None
            )
            file, file_path = self.build_file(html, file_name, self.preview)
            generated = GeneratedReport(
                path=file_path,
                file_name=file_name,
                professional_id=self.current_professional.id,
                entity_id=self.current_entity.id if self.current_entity else None,
                custom_report=self.template,
                file=file
            )
            self.remove_generated_files()
        return generated if generated else None

    def build_html_template_and_file_name(self, entity_name: str = None) -> Tuple[str, str]:
        html = self.template.html_template
        html = self.replace_template_blocks(html)
        html = self.replace_template_visit_answers(html)
        html = self.replace_client_custom_blocks(html)
        if not entity_name:
            file_name = '{}--{}.pdf'.format(self.current_professional.id, uuid.uuid4())
        else:
            file_name = '{}--{}--{}.pdf'.format(self.current_professional.id, unidecode(entity_name), uuid.uuid4())
        return html, file_name

    def build_file(self, html: str, file_name: str, remove_preview: bool = False) -> Tuple[bytes, str]:
        file_path = settings.TEMPORAL_DIR + file_name
        HTML(string=html, base_url=settings.DOMAIN).write_pdf(presentational_hints=True, target=file_path)
        if remove_preview:
            self.generated_files.append(file_path)
        if self.template.append_annexes:
            pdf_file, file_path = self.get_report_with_merged_annexes(file_name, file_path)
        else:
            pdf_file = open(file_path, 'rb').read()
        return pdf_file, file_path

    def replace_template_blocks(self, template: str) -> str:
        base = '<span class="h-card" style="color:blue">{}</span>'
        blocks = {
            '[[professionalName]]': lambda: self.current_professional.usuario.persona.nombre,
            '[[professionalLastName]]': lambda: self.current_professional.usuario.persona.apellido or '',
            '[[professionalGender]]': lambda: self.current_professional.usuario.persona.genero or '',
            '[[professionalEmail]]': lambda: self.current_professional.usuario.persona.email or '',
            '[[professionalPhone]]': lambda: self.current_professional.usuario.persona.telefono or '',
            '[[reportPeriod]]': lambda: self.get_report_period_block(),
            '[[reportDate]]': lambda: datetime.now().strftime('%d-%m-%Y')
        }
        blocks = self.set_additional_info_blocks(blocks)
        for key in blocks.keys():
            block = base.format(key)
            if block in template:
                template = template.replace(block, blocks[key]())
        return template

    def set_additional_info_blocks(self, blocks: Dict[str, Any]) -> Dict[str, Any]:
        professional_keys = self.client.profesionales_informacion_adicional or []
        for key in professional_keys:
            blocks['[[{}]]'.format(key)] = partial(self.get_professional_additional_info_key, key)
        return blocks

    def replace_template_visit_answers(self, template: str) -> str:
        for item in re.findall(r'<span class="h-card" style="color:blue">\[\[qID(.+?)]]</span>', template):
            data = item.split(':')
            values = data[0].split('-')
            option = self.get_list_index_or_none(data, 1)
            replace_value = ''
            if len(values) == 3 and option:
                replace_value = self.get_question_answer_by_option(values, option)
            template = template.replace(
                '<span class="h-card" style="color:blue">[[qID{}]]</span>'.format(item),
                replace_value
            )
        return template

    def get_question_answer_by_option(self, values, option) -> str:
        rule_id, chapter_id, question_id = values
        options = {
            '$first': lambda: self.handle_options_first_last(
                self.visits[rule_id], chapter_id, question_id, order_by='fecha'
            ),
            '$firstNull': lambda: self.handle_options_first_last(
                self.visits[rule_id], chapter_id, question_id, order_by='fecha', nullable=True
            ),
            '$last': lambda: self.handle_options_first_last(
                self.visits[rule_id], chapter_id, question_id, order_by='-fecha'
            ),
            '$lastNull': lambda: self.handle_options_first_last(
                self.visits[rule_id], chapter_id, question_id, order_by='-fecha', nullable=True
            ),
            '$average': lambda: self.handle_options_average_sum(
                self.visits[rule_id], chapter_id, question_id, option
            ),
            '$sum': lambda: self.handle_options_average_sum(
                self.visits[rule_id], chapter_id, question_id, option
            ),
            '$all': lambda: self.handle_option_all(
                self.visits[rule_id], chapter_id, question_id
            )
        }
        return options.get(option)()

    def handle_options_first_last(self, visits: QuerySet[Fiscalizacion],
                                  chapter_id: str,
                                  question_id: str,
                                  order_by: str,
                                  nullable: bool = False) -> str:
        visits = visits.order_by(order_by)
        for visit in visits:
            answer = self.get_chapter_answer_by_visit(visit, chapter_id, question_id)
            if answer or nullable:
                return answer
        return ''

    def handle_options_average_sum(self, visits: QuerySet[Fiscalizacion],
                                   chapter_id: str,
                                   question_id: str,
                                   option: str) -> str:
        total, count = 0, 0
        for visit in visits:
            answer = self.get_chapter_answer_by_visit(visit, chapter_id, question_id)
            if answer:
                total += ast.literal_eval(answer)
                count += 1
        if option == '$average':
            return '{:.2f}'.format(total / count)
        if option == '$sum':
            return str(total)
        return ''

    def set_current_professional_visits(self, entity_id: int = None) -> None:
        now = datetime.now() if not self.custom_date else self.custom_date
        start_date = (now - timedelta(days=self.template.use_data_from_days)).strftime('%Y-%m-%d')
        end_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        for rule_id in self.template.rule_ids:
            filter_data = {'norma__pk': rule_id,
                           'fecha__range': [start_date, end_date],
                           'profesional_id': self.current_professional.id}
            if entity_id:
                filter_data['entidad_id'] = entity_id
            self.visits[str(rule_id)] = Fiscalizacion.objects.using(settings.REPORTING_CORE_DB).filter(
                **filter_data
            ).select_related(
                'entidad', 'entidad__productor', 'entidad__productor__persona', 'profesional',
                'profesional__usuario', 'profesional__usuario__persona'
            ).order_by('pk')
        return None

    def get_report_with_merged_annexes(self, file_name: str, file_path: str) -> Tuple[bytes, str]:
        for rule_id in self.template.append_annexes_rules:
            for visit in self.visits[str(rule_id)]:
                self.download_annexes_to_append(visit)
        if len(self.generated_files) > 0:
            merged_path = self.merge_report_with_annexes(file_name, file_path)
            merged_file = open(merged_path, 'rb').read()
            return merged_file, merged_path
        file = open(file_path, 'rb').read()
        return file, file_path

    def download_annexes_to_append(self, visit: Fiscalizacion):
        question_annexes = list(
            filter(lambda i: i['pregunta'] in self.template.append_annexes_questions, visit.anexos or [])
        )
        for annex in question_annexes:
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
                    remove_generated_file(downloaded_path)
        return None

    def merge_report_with_annexes(self, file_name: str, pdf_path: str) -> str:
        files = self.generated_files if self.preview else [pdf_path, *self.generated_files]
        merger = PdfMerger()
        for file_path in files:
            try:
                merger.append(file_path)
            except:
                pass
        joined_path = settings.TEMPORAL_DIR + file_name
        merger.write(joined_path)
        merger.close()
        return joined_path

    def professional_has_visits(self) -> bool:
        counter = 0
        for rule_id in self.template.rule_ids:
            counter = counter + 1 if self.visits[str(rule_id)].count() > 0 else counter
        return counter > 0

    def remove_generated_files(self) -> None:
        for path in self.generated_files:
            remove_generated_file(path)
        return None
