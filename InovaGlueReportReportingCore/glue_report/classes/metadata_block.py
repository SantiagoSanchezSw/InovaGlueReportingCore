from reporting_core.classes import BaseReport
from django.template import Template, Context
from django.conf import settings
import re
# Models
from inova_core.models import Pregunta


class MetadataBlock(BaseReport):
    def replace_html_metadata_blocks(self, template: str) -> str:
        if template is not None:
            for item in re.findall(
                    r'<span class="h-card" style="color:blue">\[\[metadataBlock([0-9-?]+)]]</span>',
                    template
            ):
                values = item.split('-')
                replace_value = ''
                visit_chapter = self.get_item('capitulo', 'pk', int(values[0]), self.visit.capitulos)
                if visit_chapter:
                    visit_answer = self.get_item('pregunta', 'pk', int(values[1]), visit_chapter['respuestas'])
                    question = Pregunta.objects.using(settings.REPORTING_CORE_DB).get(pk=values[1])
                    try:
                        html = Template(question.metadata['reportBlockTemplate']['template'])
                        context = {'object': visit_answer}
                        replace_value = html.render(Context(context))
                    except Exception as e:
                        pass
                template = template.replace(
                    '<span class="h-card" style="color:blue">[[metadataBlock{}]]</span>'.format(item),
                    replace_value
                )
            return template
        pass
