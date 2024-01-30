from django.conf import settings
from django.template.loader import render_to_string, get_template
from weasyprint import HTML
from datetime import timedelta
import uuid
import re
# Models
from inova_core.models import Fiscalizacion, Pregunta, Cliente
from reporting_core.models import CustomReport, Report, ReportGeneration
# Classes
from reporting_core.classes import InOvaReport, ReportCode, MetadataBlock
# Types
from typing import Any, Optional, Dict, List
from reporting_core.types import GeneratedReport, CustomReportCondition
# Helpers
from inova_base.helpers.user.client import get_client_language
from reporting_core.helpers.report import rename_report, report_or_visit_changed, create_or_update_report
# Constants
from inova_core.constants.question import question_type
# Enums
from reporting_core.enums import Condition, ConditionType
from reporting_core.classes import AWSClient
# request
from django.template import Context
# Base
from inova_base.helpers.boto3_helper import generate_s3_temp_url


class HTMLReport(InOvaReport,
                 ReportCode,
                 MetadataBlock):
    visit: Fiscalizacion
    template: str
    preview: bool = False
    client: Cliente
    language: Dict[str, Any]
    custom_report: CustomReport
    USE_GLUE: bool = True

    def __init__(self, template: CustomReport, client: Cliente, visit: Optional[Fiscalizacion] = None):
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
        self.custom_report = template
        self.template = template.html_template

    def generate(self) -> GeneratedReport:
        if self.visit.norma.metadata and 'ReportImageCodes' in self.visit.norma.metadata:
            # generate a lambda report
            report_url = self.build_report_in_lambda(self.visit, self.client, self.custom_report)
            file_name = '{}.pdf'.format(uuid.uuid4())
            file_path = settings.TEMPORAL_DIR + file_name
            if report_url is not None:
                return GeneratedReport(
                    path=report_url,
                    file_name=file_name,
                    file=report_url,
                    custom_report=self.custom_report
                )
            else:
                return 'Something when wrong please contact the administrator.'
            
        if self.template is not None:
            self.language = get_client_language(self.client, using=settings.REPORTING_CORE_DB)
            self.template = self.replace_template_blocks(self.template)
            self.template = self.replace_template_operation_blocks(self.template)
            self.template = self.replace_client_info(self.template)
            self.template = self.replace_template_visit_answers(self.template)
            self.template = self.replace_composed_signatures(self.template)
            self.template = self.replace_html_metadata_blocks(self.template)
            self.template = self.replace_location_values(self.template)
        file_name = '{}.pdf'.format(uuid.uuid4())
        file_path = settings.TEMPORAL_DIR + file_name
        pdf_file = HTML(
            string=self.template if self.template is not None else '', base_url=settings.DOMAIN
        ).write_pdf(
            presentational_hints=True,
            target=file_path if not self.preview else None
        )
        return GeneratedReport(
            path=file_path if not self.preview else None,
            file_name=file_name,
            file=pdf_file,
            custom_report=self.custom_report
        )


    def build_report_in_lambda(self, visit, client, custom_report):
        print("EL CUSTOM REPORT QUE LLEGA", custom_report)
        report_request = ReportGeneration.objects.create(
            visit_id=visit.pk,
            client_id=client.pk,
            custom_report=custom_report,
        )
        lambda_response = AWSClient(service='lambda').invoke_function(
            function_name=settings.GENERATE_REPORT_FUNCTION_NAME,
            invocation_type='RequestResponse',
            payload={'pathParameters': {'id': report_request.pk}}
        )
        print("PASA LA LAMBDA", visit.pk, visit.norma_id)
        print("ENTRA POR ACA")
        custom_report_qs = self.get_custom_report(custom_report, client, visit)
        print("TIENE CUSTOM REPORT?", custom_report_qs)
        custom_report = custom_report_qs.first() if custom_report_qs and custom_report_qs.exists() else None
        print("EL CUSTOM REPORT", custom_report)
        qs = Report.objects.filter(visit_id=visit.pk, rule_id=visit.norma_id)
        print("EL QUERYSET deberia funcionar men", qs)
        if custom_report and not report_or_visit_changed(qs, visit, custom_report):
            report_url = rename_report(qs.first().url, client, visit, custom_report)
            return generate_s3_temp_url(report_url)
        print("LA URL DEL REPORTE", generate_s3_temp_url(qs.first().url))
        return generate_s3_temp_url(qs.first().url)

    
    def get_custom_report(self, custom_report, client, visit):
        if custom_report is not None:
            custom_report = CustomReport.objects.filter(pk=custom_report.pk)
        else:
            custom_report_qs = CustomReport.objects.filter(client_id=client.pk, rule_id=visit.norma_id, default=True)
            custom_report = custom_report_qs if custom_report_qs.exists() else None
        return custom_report


    def replace_template_blocks(self, template: str):
        base = '<span class="h-card" style="color:blue">{}</span>'
        blocks = self.get_basic_info_blocks()
        blocks.update({
            '[[chapters]]': lambda: self.render_to_string_chapters_block(),
            '[[signatures]]': lambda: self.render_to_string_signatures_block(),
            '[[annexes]]': lambda: self.render_to_string_annexes_block(),
            '[[workPlan]]': lambda: self.render_to_string_work_plan_block(),
            '[[recommendations]]': lambda: self.render_to_string_recommendations_block(),
            '[[classifications]]': lambda: self.render_to_string_classifications_block()
        })
        for key in blocks.keys():
            block = base.format(key)
            if block is not None and template is not None and block in template:
                template = template.replace(block, blocks[key]())
        return template

    def replace_template_operation_blocks(self, template: str) -> str:
        if template is not None:
            for item in re.findall(r'<span class="h-card" style="color:blue">\[\[date\+([0-9?]+)]]</span>', template):
                replace_value = (self.visit.fecha + timedelta(days=int(item))).strftime('%d/%m/%Y')
                template = template.replace(
                    '<span class="h-card" style="color:blue">[[date+{}]]</span>'.format(item),
                    replace_value
                )
            return template
        else:
            pass

    def replace_client_info(self, template: str) -> str:
        if template is not None:
            for item in re.findall(r'<span class="h-card" style="color:blue">\[\[qID([0-9?]+)]]</span>', template):
                entity_info = self.visit.entidad.informacion_general
                if entity_info is not None:
                    replace_value = self.get_answer_in_chapter(entity_info, int(item))
                    template = template.replace(
                        '<span class="h-card" style="color:blue">[[qID{}]]</span>'.format(item),
                        replace_value
                    )
            return template
        pass

    def replace_template_visit_answers(self, template: str) -> str:
        if template is not None:
            for item in re.findall(r'<span class="h-card" style="color:blue">\[\[qID([0-9-?]+)]]</span>', template):
                values = item.split('-')
                replace_value = ''
                visit_chapter = self.get_item('capitulo', 'pk', int(values[0]), self.visit.capitulos)
                if visit_chapter:
                    answer_value = self.get_answer_in_chapter(visit_chapter['respuestas'], int(values[1]))
                    replace_value = self.get_conditional_answer_value(answer_value, values[1])
                    if isinstance(replace_value, list):
                        replace_value = self.render_compound_question_block(replace_value,
                                                                            int(values[1]),
                                                                            visit_chapter['respuestas'])
                template = template.replace(
                    '<span class="h-card" style="color:blue">[[qID{}]]</span>'.format(item),
                    replace_value
                )
            return template
        pass

    def get_conditional_answer_value(self, answer_value: str, question_id: str) -> str:
        if self.custom_report.conditionals and question_id in self.custom_report.conditionals:
            for conditional in self.custom_report.conditionals[question_id]:
                types = {
                    ConditionType.DEFAULT_VALUE: lambda: self.handle_conditional_default_value(conditional,
                                                                                               answer_value),
                    ConditionType.OVERRIDE: lambda: self.handle_conditional_override_hide(conditional, answer_value),
                    ConditionType.HIDE: lambda: self.handle_conditional_override_hide(conditional, answer_value)
                }
                answer_value = answer_value = types.get(conditional['type'], '')()
        return answer_value

    def handle_conditional_default_value(self, conditional: CustomReportCondition, answer_value: str) -> str:
        if not answer_value:
            return str(conditional['value'])
        return answer_value

    def handle_conditional_override_hide(self, conditional: CustomReportCondition, answer_value: str) -> str:
        if any([
            conditional['condition'] == Condition.EQUALS and answer_value == str(conditional['answer']),
            conditional['condition'] == Condition.DIFFERENT and answer_value != str(conditional['answer']),
            conditional['condition'] == Condition.GTE and float(answer_value) >= float(conditional['answer']),
            conditional['condition'] == Condition.LTE and float(answer_value) <= float(conditional['answer'])
        ]):
            return '' if conditional['type'] == 'HIDE' else str(conditional['value'])
        return answer_value

    def replace_composed_signatures(self, template: str) -> str:
        if template is not None:
            for item in re.findall(r'<span class="h-card" style="color:blue">\[\[composedSignatures([0-9-?]+)]]</span>',
                                   template):
                values = item.split('-')
                if len(values) == 3:
                    chapter_id = int(values[0])
                    composed_question_id = int(values[1])
                    sub_question_id = int(values[2])
                    replace_value = ''
                    visit_chapter = self.get_item('capitulo', 'pk', chapter_id, self.visit.capitulos)
                    if visit_chapter:
                        composed_answer = self.get_answer_in_chapter(visit_chapter['respuestas'], composed_question_id)
                        if isinstance(composed_answer, list):
                            signatures = []
                            for items in composed_answer:
                                items_value = items['items']
                                sub_answer = list(
                                    filter(lambda d: d['subpregunta']['pk'] == sub_question_id, items_value))
                                sub_answer = sub_answer[0] if len(sub_answer) > 0 else None
                                if sub_answer and 'firma' in sub_answer['valor']:
                                    signatures.append(sub_answer['valor'])
                            replace_value = self.render_to_string_composed_signatures(signatures)
                    template = template.replace(
                        '<span class="h-card" style="color:blue">[[composedSignatures{}]]</span>'.format(item),
                        replace_value
                    )
            return template
        pass

    def render_to_string_chapters_block(self) -> str:
        if self.USE_GLUE:

            context = Context({'capitulos': self.visit.capitulos,
                               'tipo': question_type,
                               'object': self.visit,
                               'idiom': self.get_client_idiom_keys(),
                               'visibles_norma': Pregunta.objects.using(
                                   settings.REPORTING_CORE_DB
                               ).filter(
                                   opciones__visible_pdf=True,
                                   capitulo__norma__pk=self.visit.norma_id
                               ).values_list('pk', flat=True)})
            html_template = get_template('_block_chapters.html').render(context)
            return html_template
        else:
            return render_to_string('_block_chapters.html', {'capitulos': self.visit.capitulos,
                                                             'tipo': question_type,
                                                             'object': self.visit,
                                                             'idiom': self.get_client_idiom_keys(),
                                                             'visibles_norma': Pregunta.objects.using(
                                                                 settings.REPORTING_CORE_DB
                                                             ).filter(
                                                                 opciones__visible_pdf=True,
                                                                 capitulo__norma__pk=self.visit.norma_id
                                                             ).values_list('pk', flat=True)})

    def render_to_string_composed_signatures(self, signatures: List[dict]) -> str:
        if self.USE_GLUE:
            context = Context({'signatures': signatures})
            html_template = get_template('_block_composed_signatures.html').render(context)
            return html_template
        else:
            return render_to_string('_block_composed_signatures.html', {'signatures': signatures})

    def render_to_string_annexes_block(self) -> str:
        if self.USE_GLUE:
            context = Context({'anexos': self.build_annexes()})
            html_template = get_template('_block_annexes.html').render(context)
            return html_template
        else:
            return render_to_string('_block_annexes.html', {'anexos': self.build_annexes()})

    def render_to_string_signatures_block(self) -> str:
        professional_name = None
        if self.visit.profesional:
            professional_name = self.get_person_name(self.visit.profesional.usuario.persona)
        context = Context({'object': self.visit, 'professional': professional_name, 'lenguaje': self.language,
                           'firmas': self.build_signatures()})
        html_template = get_template('_block_signatures.html').render(context)
        return html_template

    def render_to_string_work_plan_block(self) -> str:
        if self.USE_GLUE:
            context = Context({'plan_de_trabajo': self.build_work_plan(), 'lenguaje': self.language})
            html_template = get_template('_block_work_plan.html').render(context)
            return html_template
        else:
            return render_to_string('_block_work_plan.html',
                                    {'plan_de_trabajo': self.build_work_plan(), 'lenguaje': self.language})

    def render_to_string_recommendations_block(self) -> str:
        if self.USE_GLUE:
            context = Context({'capitulos': self.build_chapters()})
            html_template = get_template('_block_recommendations.html').render(context)
            return html_template
        else:
            return render_to_string('_block_recommendations.html', {'capitulos': self.build_chapters()})

    def render_to_string_classifications_block(self) -> str:
        if self.USE_GLUE:
            context = Context({'calificacion': self.build_calification(), 'lenguaje': self.language})
            html_template = get_template('_block_classifications.html').render(context)
            return html_template
        else:
            return render_to_string('_block_classifications.html',
                                    {'calificacion': self.build_calification(), 'lenguaje': self.language})

    def render_compound_question_block(self,
                                       compound_value: List[Dict[str, Any]],
                                       question_id: int,
                                       chapter_answers: List[Dict[str, Any]]) -> str:
        question = Pregunta.objects.using(settings.REPORTING_CORE_DB).get(pk=question_id)
        sub_questions = question.compuesta.subpreguntas.filter(
            versiones__contains=[self.visit.norma.version]
        ).order_by('orden', 'pk')
        result_questions = list(
            filter(lambda i: i['pregunta']['tipo'] == question_type.RESULT, chapter_answers)
        )
        if len(result_questions) > 0:
            for result_q in result_questions:
                result_question_data = question.compuesta.resultado_set.filter(
                    pregunta__id=result_q['pregunta']['pk']).first()
                if result_question_data:
                    result_q['pregunta']['subpregunta'] = result_question_data.subpregunta_id
        if self.USE_GLUE:
            context = Context({'result_questions': result_questions,
                               'compound_value': compound_value,
                               'question': question,
                               'sub_questions': sub_questions,
                               'sub_questions_ids': sub_questions.values_list('pk', flat=True),
                               'tipo': question_type,
                               'chapter_answers': chapter_answers,
                               'general_info': self.visit.entidad.informacion_general,
                               'idiom': self.language})
            html_template = get_template('_block_compound.html').render(context)
            return html_template
        else:
            return render_to_string('_block_compound.html', {'result_questions': result_questions,
                                                             'compound_value': compound_value,
                                                             'question': question,
                                                             'sub_questions': sub_questions,
                                                             'sub_questions_ids': sub_questions.values_list('pk',
                                                                                                            flat=True),
                                                             'tipo': question_type,
                                                             'chapter_answers': chapter_answers,
                                                             'general_info': self.visit.entidad.informacion_general,
                                                             'idiom': self.language})

    def replace_location_values(self, template: str) -> str:
        if template is not None:
            if self.visit.entidad:
                entity_values = self.visit.entidad.valores
                entity_layers = dict()
                if entity_values and 'insideLayers' in entity_values:
                    entity_layers = entity_values['insideLayers']
                for item in re.findall(r'<span class="h-card" style="color:blue">\[\[inLayer:([a-zA-Z0-9?=]+)]]</span>',
                                       template):
                    inside_Layer = 'Si' if entity_layers.get(item, False) else 'No'
                    template = template.replace(
                        '<span class="h-card" style="color:blue">[[inLayer:{}]]</span>'.format(item),
                        inside_Layer
                    )
            return template
        pass
