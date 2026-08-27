#!/usr/bin/env python3
"""Several inputs reach the model as one job, with the rule they broke.

The behaviour this guards
-------------------------
The converter was per-file: one profile, one "Input path", one script. The
failure that reached a guest on 2026-08-27 (job q603AOxICD) is not in any one
file -- a one-column proteomics fold change beside a fourteen-column lipidomics
table, each valid alone, refused together because PaintOmics paints every omic
on the same conditions. Handed either file, with the other's header as
context, the agent rightly found nothing to fix and said so; the user read
that as "the AI fix does not work".

So `build_user_message` now takes `state["inputs"]`: every values file of the
job, each with its omic, its width and its own profile, rendered under one
"## Inputs" heading; and the system prompt carries a section that states the
rule and how to satisfy it -- reduce the wider omic to the narrower one's
shape by deriving (means, ratios) from its own columns, never pad, ask when the
data cannot settle the grouping or the direction, and declare every output
with "for": <input path>.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_harmonise_prompt
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.InputConvert.prompts import SYSTEM_PROMPT, build_user_message


def _twoInputs():
    return {
        "goal": "Make these omics agree.",
        "species": "ecb",
        "inputs": [
            {"path": "/work/vp_fc_values.tab", "omic": "Proteomics", "fileName": "vp_fc_values.tab",
             "role": "values", "conditions": 1,
             "profile": {"tables": [{"name": "(single table)", "n_columns": 2}]}},
            {"path": "/work/lipidomica_samples.tab", "omic": "Metabolomics",
             "fileName": "lipidomica_samples.tab", "role": "values", "conditions": 14,
             "profile": {"tables": [{"name": "(single table)", "n_columns": 15}]}},
        ],
        "instructions": ["PaintOmics refused this job. It said: Every omic in one run must "
                         "have the same number of conditions."],
    }


class SystemPromptTest(unittest.TestCase):

    def test_the_rule_is_stated_with_its_remedy(self):
        section = SYSTEM_PROMPT[SYSTEM_PROMPT.index("MAKING THE OMICS AGREE"):]
        self.assertIn("SAME NUMBER of\ncondition columns", section)
        self.assertIn("FEWEST condition columns", section)
        self.assertIn("Deriving is allowed here, and only here", section)
        self.assertIn("Never widen the narrow omic", section)
        self.assertIn('"for": "<that input\'s path exactly as listed>"', section)
        self.assertIn('"unchanged": true', section)

    def test_ratio_versus_log_ratio_is_decided_by_the_narrow_omic(self):
        """The reported proteomics FC is a plain ratio (values up to 1000, all
        positive); a log2 of the lipid means would not have matched it."""
        section = SYSTEM_PROMPT[SYSTEM_PROMPT.index("MAKING THE OMICS AGREE"):]
        self.assertIn("plain ratios", section)
        self.assertIn("log2 of that ratio", section)

    def test_the_single_file_paragraph_points_at_the_section(self):
        self.assertIn("read the section\nMAKING THE OMICS AGREE", SYSTEM_PROMPT)


class UserMessageTest(unittest.TestCase):

    def test_every_input_is_listed_with_its_omic_and_width(self):
        message = build_user_message(_twoInputs())
        self.assertIn("## Inputs (2 files of one run", message)
        self.assertIn("### Input 1: /work/vp_fc_values.tab", message)
        self.assertIn("omic: Proteomics", message)
        self.assertIn("condition columns: 1", message)
        self.assertIn("### Input 2: /work/lipidomica_samples.tab", message)
        self.assertIn("omic: Metabolomics", message)
        self.assertIn("condition columns: 14", message)

    def test_each_input_carries_its_own_profile(self):
        message = build_user_message(_twoInputs())
        self.assertIn('"n_columns": 2', message)
        self.assertIn('"n_columns": 15', message)

    def test_the_single_file_headings_are_absent(self):
        """One "Input path" and one "What the file looks like" would tell the
        model there is one file, which is the misreading being fixed."""
        message = build_user_message(_twoInputs())
        self.assertNotIn("Input path:", message)
        self.assertNotIn("## What the file looks like", message)

    def test_the_servers_words_still_reach_it(self):
        message = build_user_message(_twoInputs())
        self.assertIn("PaintOmics refused this job", message)

    def test_a_single_file_state_is_unchanged(self):
        message = build_user_message({"inputPath": "/work/a.tab", "fileName": "a.tab",
                                      "omicType": "Gene expression", "profile": {"x": 1}})
        self.assertIn("Input path: /work/a.tab", message)
        self.assertIn("## What the file looks like", message)
        self.assertNotIn("## Inputs", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
