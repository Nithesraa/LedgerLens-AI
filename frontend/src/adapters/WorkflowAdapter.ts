import type { WorkflowOutput, WorkflowCase, DemoStoryCase, WorkflowSummary } from '../types/workflow';

/**
 * Adapter to safely fetch and validate workflow runtime artifacts.
 * It strictly performs NO business logic, AI decisions, or rules processing.
 */
export class WorkflowAdapter {
  /**
   * Loads the workflow dataset for a given split (dev, validation, holdout)
   */
  static async loadWorkflowData(split: 'dev' | 'validation' | 'holdout'): Promise<WorkflowOutput> {
    const url = `/data/${split}.json`;
    try {
      const response = await fetch(url);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      
      this.validateWorkflowSchema(data);
      
      return data as WorkflowOutput;
    } catch (error) {
      console.error(`Failed to load workflow data for split: ${split}`, error);
      throw new Error(`Failed to load workflow data: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  /**
   * Performs lightweight structural validation of untrusted JSON.
   */
  private static validateWorkflowSchema(data: any): void {
    if (!data) {
      throw new Error('Data is empty or null');
    }
    
    if (!data.run_metadata || typeof data.run_metadata.split !== 'string') {
      throw new Error('Missing or malformed run_metadata');
    }
    
    if (!data.summary || typeof data.summary.total_cases !== 'number') {
      throw new Error('Missing or malformed summary');
    }
    
    if (!Array.isArray(data.cases)) {
      throw new Error('Cases is not an array');
    }

    if (data.cases.length > 0) {
      const firstCase = data.cases[0];
      if (!firstCase.operational_reference_id) {
        throw new Error('Case missing operational_reference_id');
      }
      if (!firstCase.reconciliation || typeof firstCase.reconciliation.route !== 'string') {
        throw new Error('Case missing or malformed reconciliation object');
      }
      if (!firstCase.execution || typeof firstCase.execution.status !== 'string') {
        throw new Error('Case missing or malformed execution object');
      }
    }
  }

  /**
   * Retrieves all cases from the loaded workflow output.
   */
  static getCases(workflowData: WorkflowOutput): WorkflowCase[] {
    return workflowData.cases;
  }

  /**
   * Retrieves a specific case by its operational reference ID.
   */
  static getCaseByReference(workflowData: WorkflowOutput, referenceId: string): WorkflowCase | null {
    return workflowData.cases.find(c => c.operational_reference_id === referenceId) || null;
  }

  /**
   * Retrieves the pre-curated demo story cases.
   * Assumes the backend remains the authority on which cases demonstrate specific scenarios.
   */
  static getDemoCases(workflowData: WorkflowOutput): DemoStoryCase[] {
    return workflowData.demo_story_cases || [];
  }

  /**
   * Retrieves the summary metrics.
   */
  static getSummary(workflowData: WorkflowOutput): WorkflowSummary {
    return workflowData.summary;
  }
}
