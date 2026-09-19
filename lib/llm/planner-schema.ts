import { z } from 'zod';

export const robotActionSchema = z.object({
  action: z.enum([
    'MOVE_VELOCITY',
    'ROTATE_JOINT',
    'AWAIT_CONDITION',
    'ATTACH_COMPONENT',
    'SET_POSE',
    'WAIT',
  ]),
  params: z.record(z.any()).default({}),
  condition: z.enum(['SENSOR_RAYCAST', 'SENSOR_PROXIMITY', 'JOINT_LIMIT', 'TIME_ELAPSED']).optional(),
  on_true: z.string().optional(),
});

export const executionPlanSchema = z.object({
  summary: z.string(),
  steps: z.array(robotActionSchema),
});

export type RobotAction = z.infer<typeof robotActionSchema>;
export type ExecutionPlan = z.infer<typeof executionPlanSchema>;
