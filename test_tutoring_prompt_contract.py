"""Exercise the real prompt assembly using synthetic context and no model calls."""
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
from services.agent.agents.tutor import TutorAgent
from services.agent.agents import prompts
from services.agent.prompt_loader import render_prompt,clear_cache
from services.agent.skills import load_skills
from services.agent.state import AgentContext

class TutoringPromptContractTests(unittest.TestCase):
 def context(self,message="Teach me integer division",**kwargs):
  return AgentContext(user_id=uuid.UUID(int=1),course_id=uuid.UUID(int=2),user_message=message,**kwargs)
 def build(self,ctx):
  with patch("services.agent.tool_loader.get_scene_tools",return_value=""):
   return TutorAgent().build_system_prompt(ctx)
 def test_live_tutor_fallback_teaches_foundations_without_requiring_a_template(self):
  text=self.build(self.context())
  self.assertIn("explain the\n  foundations first",text)
  self.assertIn("different inputs from the pending exercise",text)
  self.assertIn("not an invented numerical mastery score",text)
 def test_prompt_update_preserves_materials_and_existing_learner_preferences(self):
  text=self.build(self.context(preferences={"language":"zh","detail_level":"concise"},content_docs=[{"title":"Synthetic example","source_file":"synthetic_notes.md","content":"A toy integer division example."}]))
  self.assertIn("synthetic_notes.md",text);self.assertIn("A toy integer division example.",text)
  self.assertIn("language: zh",text);self.assertIn("detail_level: concise",text)
 def test_template_path_also_receives_foundation_and_hint_guidance(self):
  with patch("services.agent.prompt_loader.render_prompt",return_value="SYNTHETIC TEMPLATE"):
   text=self.build(self.context())
  self.assertIn("SYNTHETIC TEMPLATE",text);self.assertIn("one small\n  hint",text)
 def test_error_review_uses_evidence_and_preserves_same_task_retry(self):
  text=self.build(self.context("review my mistake",metadata={"error_detail":{"category":"computational","evidence":"Synthetic incomplete operation","confidence":0.5}}))
  self.assertIn("allow the same task to be retried",text)
  self.assertIn("verify against current evidence",text)
  self.assertIn("state uncertainty",text)
  self.assertNotIn("Show the correct approach step by step",text)
  self.assertNotIn("treat it as ground truth",text)
 def test_practice_retains_private_generation_schema_and_subject_skill_guidance(self):
  text=self.build(self.context("generate quiz questions"))
  self.assertIn("question_type, question, options, correct_answer, explanation",text)
  self.assertIn("private assessment data",text)
  self.assertIn("predicting output",text)
 def test_frustration_path_remains_supportive_without_mandatory_probing(self):
  text=self.build(self.context("I am frustrated",metadata={"fatigue_score":0.9}))
  self.assertIn("Teaching Mode: Supportive",text)
  self.assertIn("worked examples rather than questions",text)
  self.assertNotIn("## Evidence-based comprehension checks",text)
 def test_legacy_templates_render_includes_and_context(self):
  clear_cache()
  for name in ("teaching","exercise","review"):
   text=render_prompt(name,course_name="Synthetic course",scene="study_session",memory_section="Synthetic memory",tutor_notes_section="")
   self.assertIn("Synthetic course",text);self.assertNotIn("{{include:",text)
 def test_strategy_loaders_keep_existing_fragment_names_and_yaml_metadata(self):
  prompts._STRATEGY_FRAGMENTS.clear();fragments=prompts._load_strategy_fragments()
  for name in ("socratic_questioning","worked_examples","step_by_step","math_image_tutoring"):self.assertIn(name,fragments)
  self.assertNotIn("2+ failed attempts",fragments["socratic_questioning"])
  load_skills.cache_clear();skills={skill.name:skill for skill in load_skills()}
  for name in ("socratic_questioning","error_analysis","worked_examples"):
   self.assertIn(name,skills);self.assertTrue(skills[name].triggers)
