import { useState, useEffect } from 'react';
import { WorkflowAdapter } from '../adapters/WorkflowAdapter';
import type { WorkflowOutput } from '../types/workflow';

export type SplitType = 'dev' | 'validation' | 'holdout';

export function useWorkflowData(initialSplit: SplitType = 'dev') {
  const [data, setData] = useState<WorkflowOutput | null>(null);
  const [split, setSplit] = useState<SplitType>(initialSplit);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await WorkflowAdapter.loadWorkflowData(split);
        if (mounted) {
          setData(result);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [split]);

  return { data, split, setSplit, loading, error };
}
