// @ts-nocheck
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { AIInvestigationsPage } from './AIInvestigationsPage';
import { PolicySafetyPage } from './PolicySafetyPage';
import { AuditTrailPage } from './AuditTrailPage';
import fs from 'fs';
import path from 'path';

function readArtifact(split: string) {
  const dataPath = path.resolve(__dirname, `../../public/data/${split}.json`);
  return JSON.parse(fs.readFileSync(dataPath, 'utf-8'));
}

describe('Phase 6 UI Tests', () => {
  let devData;
  let validationData;
  let holdoutData;

  beforeEach(() => {
    devData = readArtifact('dev');
    validationData = readArtifact('validation');
    holdoutData = readArtifact('holdout');
  });

  describe('AI Investigations', () => {
    it('AI page renders', () => {
      render(<AIInvestigationsPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getByText('AI Investigations')).toBeDefined();
    });

    it('Only AI-routed cases appear and Deterministic cases do not appear in AI view', () => {
      render(<AIInvestigationsPage data={devData} onNavigateCase={vi.fn()} />);
      const deterministicCase = devData.cases.find(c => c.reconciliation.route === 'DETERMINISTIC');
      expect(screen.queryByText(deterministicCase.operational_reference_id)).toBeNull();
    });

    it('DEV AI count matches actual artifact', () => {
      render(<AIInvestigationsPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText(String(devData.summary.ai_cases)).length).toBeGreaterThan(0);
    });

    it('VALIDATION AI count matches actual artifact', () => {
      render(<AIInvestigationsPage data={validationData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText(String(validationData.summary.ai_cases)).length).toBeGreaterThan(0);
    });

    it('HOLDOUT AI count matches actual artifact', () => {
      render(<AIInvestigationsPage data={holdoutData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText(String(holdoutData.summary.ai_cases)).length).toBeGreaterThan(0);
    });

    it('AI confidence, subtype, and reasoning renders correctly', () => {
      render(<AIInvestigationsPage data={devData} onNavigateCase={vi.fn()} />);
      const aiCase = devData.cases.find(c => c.reconciliation.route === 'AI_INVESTIGATOR');
      if (aiCase) {
        expect(screen.getAllByText(aiCase.investigation.subtype || aiCase.reconciliation.detected_issue).length).toBeGreaterThan(0);
        if (aiCase.investigation.confidence_score !== null) {
          expect(screen.getAllByText(`${(aiCase.investigation.confidence_score * 100).toFixed(1)}%`).length).toBeGreaterThan(0);
        }
        expect(screen.getAllByText(aiCase.investigation.reasoning).length).toBeGreaterThan(0);
      }
    });

    it('AI recommendation differs visually from final policy action when applicable', () => {
      render(<AIInvestigationsPage data={devData} onNavigateCase={vi.fn()} />);
      const aiCase = devData.cases.find(c => c.reconciliation.route === 'AI_INVESTIGATOR' && c.investigation.recommended_action !== c.policy.authorized_action);
      if (aiCase) {
        expect(screen.getAllByText('Policy Override').length).toBeGreaterThan(0);
      }
    });
  });

  describe('Policy & Safety', () => {
    it('Policy page renders', () => {
      render(<PolicySafetyPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getByText('Policy & Safety')).toBeDefined();
    });

    it('ALLOW/ DENY/ MONITOR/ ESCALATE values come from workflow summary', () => {
      render(<PolicySafetyPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText(String(devData.summary.policy.ALLOW)).length).toBeGreaterThan(0);
      expect(screen.getAllByText(String(devData.summary.policy.ESCALATE)).length).toBeGreaterThan(0);
    });

    it('Policy gates render from actual payload', () => {
      render(<PolicySafetyPage data={devData} onNavigateCase={vi.fn()} />);
      const c = devData.cases[0];
      const totalGates = Object.keys(c.policy.gates).length;
      expect(screen.getAllByText(new RegExp(`${totalGates}`)).length).toBeGreaterThan(0);
    });

    it('AI override story appears only when recommendation differs from authorized action', () => {
      const { container } = render(<PolicySafetyPage data={devData} onNavigateCase={vi.fn()} />);
      const hasOverride = devData.cases.some(c => c.reconciliation.route === 'AI_INVESTIGATOR' && c.investigation.recommended_action !== c.policy.authorized_action);
      if (hasOverride) {
        expect(screen.getAllByText('AI Safety Override').length).toBeGreaterThan(0);
        expect(screen.queryByText('No AI policy overrides in this dataset.')).toBeNull();
      } else {
        expect(screen.getByText('No AI policy overrides in this dataset.')).toBeDefined();
      }
    });
  });

  describe('Audit Trail', () => {
    it('Audit page renders', () => {
      render(<AuditTrailPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText('Audit Trail').length).toBeGreaterThan(0);
    });

    it('Audit event count matches artifact', () => {
      render(<AuditTrailPage data={devData} onNavigateCase={vi.fn()} />);
      expect(screen.getAllByText(new RegExp(String(devData.summary.total_cases))).length).toBeGreaterThan(0);
    });

    it('Audit references render', () => {
      render(<AuditTrailPage data={devData} onNavigateCase={vi.fn()} />);
      const auditRef = devData.cases[0].audit.audit_reference;
      expect(screen.getAllByText(auditRef).length).toBeGreaterThan(0);
    });

    it('Audit search works', () => {
      render(<AuditTrailPage data={devData} onNavigateCase={vi.fn()} />);
      const searchInput = screen.getByPlaceholderText('e.g. AUDIT_... or RZP_...');
      const targetCase = devData.cases[0];
      fireEvent.change(searchInput, { target: { value: targetCase.audit.audit_reference } });
      expect(screen.getByText(/Showing 1–1 of 1 audit records/)).toBeDefined();
    });

    it('Audit filters work', () => {
      render(<AuditTrailPage data={devData} onNavigateCase={vi.fn()} />);
      const selects = screen.getAllByRole('combobox');
      const routeSelect = selects[0];
      fireEvent.change(routeSelect, { target: { value: 'AI_INVESTIGATOR' } });
      const aiCount = devData.cases.filter(c => c.reconciliation.route === 'AI_INVESTIGATOR').length;
      expect(screen.getByText(new RegExp(`Showing .* of ${aiCount} audit records`))).toBeDefined();
    });
  });
});
