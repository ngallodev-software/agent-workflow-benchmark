import fs from "node:fs";

const MODEL_OUTPUT = "/output/model-output.json";
const METADATA = "/input/pass-metadata.json";
const FINAL_OUTPUT = "/output/adjudication.json";

function fail(message) {
  process.stderr.write(`invalid adjudication model output: ${message}\n`);
  process.exit(65);
}

function readJson(path) {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    fail(`${path}: ${error.message}`);
  }
}

function sameSet(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}

function validateJustification(caseId, decisionId, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`justification must be an object for ${caseId}:${decisionId}`);
  }
  const evidence = value.decisive_case_evidence;
  if (
    !Array.isArray(evidence) ||
    evidence.length < 1 ||
    evidence.length > 3 ||
    evidence.some((item) => typeof item !== "string" || !item.trim() || item.length > 320)
  ) {
    fail(
      `justification decisive_case_evidence must contain 1-3 non-empty <=320-char strings for ${caseId}:${decisionId}`
    );
  }
  if (
    typeof value.rubric_rule !== "string" ||
    !value.rubric_rule.trim() ||
    value.rubric_rule.length > 320
  ) {
    fail(`justification rubric_rule must be a non-empty <=320-char string for ${caseId}:${decisionId}`);
  }
  const ambiguities = new Set(["none", "material", "insufficient_evidence"]);
  if (!ambiguities.has(value.ambiguity)) {
    fail(`invalid justification ambiguity for ${caseId}:${decisionId}`);
  }
}


function validateLabel(decisionId, value) {
  if (decisionId === "routing.task_class") {
    const allowed = new Set([
      "implementation",
      "diagnosis",
      "review",
      "documentation",
      "other",
    ]);
    if (typeof value !== "string" || !allowed.has(value)) {
      fail(`invalid routing.task_class label: ${JSON.stringify(value)}`);
    }
    return;
  }
  if (decisionId === "routing.interaction_required") {
    if (typeof value !== "boolean") {
      fail(`invalid routing.interaction_required label: ${JSON.stringify(value)}`);
    }
    return;
  }
  if (decisionId === "routing.semantic_risk") {
    if (!Number.isInteger(value) || value < 0 || value > 2) {
      fail(`invalid routing.semantic_risk label: ${JSON.stringify(value)}`);
    }
    return;
  }
  fail(`unknown decision seam: ${decisionId}`);
}

const output = readJson(MODEL_OUTPUT);
const metadata = readJson(METADATA);
const passSchema =
  metadata.adjudication_pass_schema ||
  "agent-workflow-benchmark/decision-study-adjudication-pass/v1";
const passV2 =
  passSchema === "agent-workflow-benchmark/decision-study-adjudication-pass/v2";
if (
  passSchema !== "agent-workflow-benchmark/decision-study-adjudication-pass/v1" &&
  !passV2
) {
  fail(`unsupported adjudication pass schema: ${JSON.stringify(passSchema)}`);
}

if (!output || typeof output !== "object" || Array.isArray(output)) {
  fail("top-level result must be an object");
}
if (!Array.isArray(output.records)) {
  fail("records must be an array");
}

const byCase = new Map();
for (const record of output.records) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    fail("every record must be an object");
  }
  if (typeof record.case_id !== "string" || !record.case_id) {
    fail("every record needs a non-empty case_id");
  }
  if (byCase.has(record.case_id)) {
    fail(`duplicate case_id: ${record.case_id}`);
  }
  if (!record.labels || typeof record.labels !== "object" || Array.isArray(record.labels)) {
    fail(`labels must be an object for ${record.case_id}`);
  }
  byCase.set(record.case_id, record);
}

const expectedIds = metadata.expected_records.map((item) => item.case_id);
if (!sameSet(new Set(expectedIds), new Set(byCase.keys()))) {
  fail("case set does not exactly match the blinded adjudication view");
}

const finalRecords = [];
for (const expected of metadata.expected_records) {
  const record = byCase.get(expected.case_id);
  const actualDecisionIds = new Set(Object.keys(record.labels));
  const expectedDecisionIds = new Set(expected.decision_ids);
  if (!sameSet(actualDecisionIds, expectedDecisionIds)) {
    fail(
      `decision seam set mismatch for ${expected.case_id}; expected ` +
      `${JSON.stringify(expected.decision_ids)}, got ` +
      `${JSON.stringify(Object.keys(record.labels))}`
    );
  }
  const labels = {};
  const justifications = {};
  if (passV2) {
    if (
      !record.justifications ||
      typeof record.justifications !== "object" ||
      Array.isArray(record.justifications)
    ) {
      fail(`justifications must be an object for ${expected.case_id}`);
    }
    const actualJustificationIds = new Set(Object.keys(record.justifications));
    if (!sameSet(actualJustificationIds, expectedDecisionIds)) {
      fail(
        `justification seam set mismatch for ${expected.case_id}; expected ` +
        `${JSON.stringify(expected.decision_ids)}, got ` +
        `${JSON.stringify(Object.keys(record.justifications))}`
      );
    }
  }
  for (const decisionId of expected.decision_ids) {
    const value = record.labels[decisionId];
    validateLabel(decisionId, value);
    labels[decisionId] = value;
    if (passV2) {
      const justification = record.justifications[decisionId];
      validateJustification(expected.case_id, decisionId, justification);
      justifications[decisionId] = {
        decisive_case_evidence: [...justification.decisive_case_evidence],
        rubric_rule: justification.rubric_rule,
        ambiguity: justification.ambiguity,
      };
    }
  }
  const finalRecord = { case_id: expected.case_id, labels };
  if (passV2) finalRecord.justifications = justifications;
  finalRecords.push(finalRecord);
}

const adjudication = {
  schema: passSchema,
  study_id: metadata.study_id,
  dataset_version: metadata.dataset_version,
  protocol_version: metadata.protocol_version,
  input_view_sha256: metadata.input_view_sha256,
  adjudicator_id: metadata.adjudicator_id,
  completed_at: new Date().toISOString(),
  attestation: {
    independent: true,
    treatment_outputs_seen: false,
    other_adjudicator_labels_seen: false,
    ...(passV2 ? { other_adjudicator_justifications_seen: false } : {}),
  },
  records: finalRecords,
};

fs.writeFileSync(FINAL_OUTPUT, JSON.stringify(adjudication, null, 2) + "\n", {
  mode: 0o600,
});
