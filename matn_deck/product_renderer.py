"""Content-led compositions through the existing measured Matn deck engine."""
from copy import deepcopy
import json
from pathlib import Path
from PIL import Image
from pptx.enum.shapes import MSO_SHAPE,MSO_CONNECTOR
from pptx.dml.color import RGBColor
from pptx.util import Pt,Emu
from matn_contracts.enums import SlideType
from .deck_v2 import V2Builder,_item
from .template_renderer import _Content,DeckRenderError
from .fit import Fitter


class ProductFitter(Fitter):
    def line_height(self,style):
        # Large display glyphs extend below Carlito's measured line in the PDF
        # renderer. Reserve extra leading in the measured stack, before layout.
        return super().line_height(style)+(style.size_pt*0.08*12700 if style.size_pt>=96 else 0)

ASSETS=Path(__file__).resolve().parents[1]/'design/icons/heroicons'


def icon_name(label):
    value=label.casefold()
    for words,name in ((('regulat','legal','policy','governance'),'scale'),(('risk','safety','security'),'shield-check'),
        (('cost','economic','fund','performance'),'chart-bar'),(('environment','climate','global'),'globe-alt'),
        (('data','database'),'circle-stack'),(('skill','education','training'),'academic-cap'),
        (('date','timeline','history'),'calendar-days'),(('adopt','people','public'),'chat-bubble-left-right')):
        if any(word in value for word in words):return name
    return 'document-text'


class ProductBuilder(V2Builder):
    def __init__(self,*args,**kwargs):
        self.product_design=False;self._fallback=False
        super().__init__(*args,**kwargs)
        self.fitter=ProductFitter(safety=self.fitter.safety,natural_lines=self.fitter.natural_lines)
        self.palette=json.loads(Path(args[2]).with_name('theme.json').read_bytes())['palette']
        self.product_design=False;self._fallback=False

    def build_storyboard(self,storyboard):
        self.product_design='PRODUCT_EVIDENCE_DESIGN:v1' in storyboard.decisions
        if self.product_design:
            self.variants=deepcopy(self.variants)
            # Full statements retain their qualifiers beside a hero number.
            # Use the whole right column before considering another layout.
            self.variants['matn:kpi:hero-number']['fixed']['body']=[0.64,0,0.36,1]
            for name in ('matn:finding:two-col','matn:finding:timeline'):
                self.variants[name]['valid'].pop('requires',None)
        return super().build_storyboard(storyboard)

    def _contents(self,index,spec):
        if not self.product_design:return super()._contents(index,spec)
        title=spec.title.text
        if spec.kind=='agenda':
            return [_Content(SlideType.FINDING,title,tuple(_item(t.text) for t in spec.lines),plan_index=index)]
        if spec.kind=='section':
            return [_Content(SlideType.SECTION_DIVIDER,title,tuple(_item(t.text) for t in spec.lines),plan_index=index)]
        if spec.kind=='warning':
            return [_Content(SlideType.SOURCES,title,lines=tuple(t.text for t in spec.lines),plan_index=index)]
        if spec.kind=='closing' and not spec.bullets:
            return [_Content(SlideType.SECTION_DIVIDER,title,tuple(_item(t.text) for t in spec.lines),plan_index=index)]
        if spec.kind in ('assertion','closing'):
            items=tuple(_item((b.text.text+' '+b.text.marker).strip(),(self.unit_fact[b.unit_id],)) for b in spec.bullets)
            if spec.composition=='key_number':
                return [_Content(SlideType.KPI,title,items,kpi_fact_ids=tuple(self.number_fact[f] for f in spec.facts),plan_index=index)]
            return [_Content(SlideType.FINDING,title,items,part=spec.part,plan_index=index)]
        return super()._contents(index,spec)

    def _variant_order(self,slide_type):
        if not self.product_design or self._current is None:return super()._variant_order(slide_type)
        from .edits import layout_overrides
        if self.storyboard and self._current.plan_index in layout_overrides(self.storyboard):return super()._variant_order(slide_type)
        spec=self._spec(self._current);n=len(self._current.items)
        if self._fallback:
            if spec.kind in ('agenda','assertion','closing'):return ['matn:limitations:default','matn:executive_summary:default']
            return super()._variant_order(slide_type)
        if spec.composition=='visual_agenda':return ['matn:executive_summary:default']
        if spec.composition=='comparison':return ['matn:finding:two-col' if n==2 else 'matn:limitations:default']
        if spec.composition=='timeline':return ['matn:finding:timeline' if n>=2 else 'matn:limitations:default']
        if spec.composition=='key_number':return ['matn:kpi:hero-number']
        if spec.composition=='quote':return ['matn:limitations:default']
        if spec.composition=='closing':return ['matn:closing:default' if spec.bullets else 'matn:section_divider:default']
        if spec.composition=='grouped':return ['matn:finding:cards-3' if n==3 else 'matn:finding:grid-2x2' if n==4 else 'matn:executive_summary:default']
        return super()._variant_order(slide_type)

    def _attempts(self,content,previous):
        if not self.product_design:return super()._attempts(content,previous)
        # Density is the existing QA overflow gate, measured on complete text.
        spec=self.specs[content.plan_index]
        if spec.kind=='agenda' and len(content.items)>4:return []
        if spec.kind in ('assertion','closing') and len(content.items)>1:
            if sum(len(item.text.split()) for item in content.items)+len(content.title.split())+8>170:return []
        try:plans=super()._attempts(content,previous)
        except DeckRenderError:plans=[]
        if any(p.ok and p.fits for p in plans):return plans
        self._fallback=True
        try:
            try:fallback=super()._attempts(content,previous)
            except DeckRenderError:fallback=[]
            return plans+fallback
        finally:self._fallback=False

    def _valid(self,name,content):
        if self.product_design and self.specs[content.plan_index].composition=='key_number' and name=='matn:kpi:hero-number':
            return name not in self.exclude.get(content.plan_index,()) and super()._valid(name,content)
        return super()._valid(name,content)

    def _evaluate(self,layout,content,order,previous):
        if self.product_design and self._spec(content).composition=='quote' and any(p.name=='body' for p in layout.placeholders):
            return self._floor(self._stepped(layout,content,order,previous,'body',32,16),'assertion')
        return super()._evaluate(layout,content,order,previous)

    def _fills(self,layout,content,spec):
        fills=super()._fills(layout,content,spec)
        if not self.product_design:return fills
        story=self._spec(content)
        for key in list(fills):
            if key.startswith('item_') and key.endswith('_title') and not story.item_titles:del fills[key]
        if story.composition=='key_number':
            fact=self._number(story.facts[0])
            fills.update(kpi_value_1=[fact.value_as_written],kpi_label_1=[story.title.text],
                         body=[item.text for item in content.items])
        return fills

    def _notes(self,slide,content):
        if not self.product_design:return super()._notes(slide,content)
        spec=self._spec(content)
        lines=list(spec.notes)
        if spec.axis:lines.insert(0,'Axis: '+spec.title.text)
        lines.insert(0,'Complete verified statements are displayed; source context is retained here in notes.')
        slide.notes_slide.notes_text_frame.text='\n'.join(lines)

    def _tinted_icon(self,name,color):
        target=self.assets/('icon-'+name+'-'+color+'.png')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            mask=Image.open(ASSETS/(name+'.png')).convert('RGBA').getchannel('A')
            image=Image.new('RGBA',mask.size,'#'+color);image.putalpha(mask);image.save(target)
        return target

    def _icon(self,slide,name,x,y,size,color,description):
        path=self._tinted_icon(name,color)
        shape=slide.shapes.add_picture(str(path),x,y,width=size,height=size)
        shape.name='Navigation icon';shape._element.nvPicPr.cNvPr.set('descr',description)

    def _record(self,plan):
        super()._record(plan)
        if not self.product_design:return
        slide=self.prs.slides[-1];spec=self._spec(plan.content);color=self.palette['accent']
        if spec.kind=='title':
            # A citation-link motif, not a data graphic; kept outside text boxes.
            for y in (112,194,276):
                circle=slide.shapes.add_shape(MSO_SHAPE.OVAL,Pt(920),Pt(y),Pt(14),Pt(14))
                circle.fill.background();circle.line.color.rgb=RGBColor.from_string(color);circle.line.width=Pt(2)
                if y<276:
                    line=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Pt(927),Pt(y+14),Pt(927),Pt(y+82))
                    line.line.color.rgb=RGBColor.from_string(color);line.line.width=Pt(1.5)
        elif spec.kind=='agenda':
            for i,item in enumerate(plan.content.items,1):
                shape=next((s for s in slide.shapes if s.name==f'item_{i}'),None)
                if shape:self._icon(slide,icon_name(item.text),shape.left-Pt(56),shape.top+Pt(2),Pt(26),color,'Navigation icon for '+item.text)
        elif spec.axis:
            icon_color=self.palette['divider_text'] if spec.kind=='section' else color
            self._icon(slide,icon_name(spec.title.text),Pt(22),Pt(55),Pt(24),icon_color,'Navigation icon for '+spec.title.text)
