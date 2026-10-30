/** Persistent executions use uppercase statuses; UI classes use lowercase names. */
export function agentStepStatus(status?: string): string {
  const value = (status ?? 'PENDING').toLowerCase();
  return value === 'succeeded' ? 'completed' : value;
}
