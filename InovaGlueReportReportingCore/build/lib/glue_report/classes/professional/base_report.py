from datetime import datetime, timedelta
# Classes
from reporting_core.classes import BaseReport
# Models
from inova_core.models import Fiscalizacion, Profesional, Entidad
from reporting_core.models import ProfessionalCustomReport
# Typing

from reporting_core.types import QuerySet
from typing import List, Union, Dict


class ProfessionalBaseReport(BaseReport):
    visits: Dict[str, QuerySet[Fiscalizacion]]
    current_professional: Profesional = None
    current_entity: Entidad = None
    template: ProfessionalCustomReport
    custom_date: datetime

    def handle_option_all(self,
                          visits: QuerySet[Fiscalizacion],
                          chapter_id: str,
                          question_id: str,
                          values_list: bool = False) -> Union[str, List[str]]:
        values = []
        for visit in visits:
            answer = self.get_chapter_answer_by_visit(visit, chapter_id, question_id)
            if answer or values_list:
                values.append(answer)
        if not values_list:
            for index, value in enumerate(values):
                values[index] = '<li>{}</li>'.format(value)
            values.insert(0, '<ul>')
            values.append('</ul>')
            return ''.join(values) if len(values) > 2 else ''
        return values

    def get_chapter_answer_by_visit(self, visit: Fiscalizacion, chapter_id: str, question_id: str) -> str:
        chapter = self.get_item('capitulo', 'pk', int(chapter_id), visit.capitulos)
        if chapter:
            return self.get_answer_in_chapter(chapter['respuestas'], int(question_id))
        return ''

    def get_professional_additional_info_key(self, key: str) -> str:
        if self.current_professional.informacion_adicional:
            info = list(filter(lambda i: i['key'] == key, list(self.current_professional.informacion_adicional)))
            if info:
                return info[0]['value']
        return ''

    def get_report_period_block(self) -> str:
        now = datetime.now() if not self.custom_date else self.custom_date
        start_date = (now - timedelta(days=self.template.use_data_from_days)).strftime('%d-%m-%Y')
        end_date = now.strftime('%d-%m-%Y')
        return '{} - {}'.format(start_date, end_date)

    @staticmethod
    def get_visit_query_data_list(visits: QuerySet[Fiscalizacion], query: str) -> List[str]:
        return list(visits.values_list(query, flat=True))
