// Tipos del contrato (docs/api/openapi.yaml), generados en schema.d.ts con `npm run api:types`.
// El resto del frontend importa de aquí, no de schema.d.ts.
import type { components } from './schema'

type Schemas = components['schemas']

export type ErrorBody = Schemas['ErrorBody']
export type ErrorCode = ErrorBody['code']
/**
 * Error de la API tal como lo pinta la UI. `code` admite además un valor desconocido
 * (versión futura de la API), que usa el título genérico.
 */
export type ApiError = Omit<ErrorBody, 'code'> & { code: ErrorCode | (string & {}) }

export type ProgressStep = Schemas['ProgressStep']
export type StepNode = ProgressStep['node']
export type StepState = ProgressStep['state']

export type ConversationSummary = Schemas['ConversationSummary']
export type ConversationStatus = ConversationSummary['status']
export type ConversationOut = Schemas['ConversationOut']
export type ConversationCreateIn = Schemas['ConversationCreateIn']
export type IterateIn = Schemas['IterateIn']
export type ApproveIn = Schemas['ApproveIn']
export type PublishOutcome = Schemas['PublishOutcome']
export type ReviewPayload = Schemas['ReviewPayload']
export type VersionOut = Schemas['VersionOut']
export type ArtifactOut = Schemas['Artifact']

export type SessionOut = Schemas['SessionOut']
export type UserOut = Schemas['UserOut']
export type Role = UserOut['role']
export type LoginIn = Schemas['LoginIn']

export type ProjectsOut = Schemas['ProjectsOut']
export type ProjectSummary = Schemas['ProjectSummary']
export type ChooseProjectIn = Schemas['ChooseProjectIn']
export type ChooseProjectOut = Schemas['ChooseProjectOut']
export type SourcesIn = Schemas['SourcesIn']
export type SourcePreview = Schemas['SourcePreview']
export type SourcesOut = Schemas['SourcesOut']
export type ContextBudget = Schemas['ContextBudgetOut']
export type IssueSummary = Schemas['IssueSummary']
export type IssueCard = Schemas['IssueCard']
export type ProposeIn = Schemas['ProposeIn']
export type StartProposal = Schemas['StartProposal']
export type StartOption = Schemas['StartOption']
export type OriginIn = Schemas['OriginIn']

export type SettingsOut = Schemas['SettingsOut']
export type UsageTodayOut = Schemas['UsageTodayOut']
export type HandoffOut = Schemas['HandoffOut']
export type TestSuite = Schemas['TestSuite']
export type TestCase = Schemas['TestCase']
export type MemorySummary = Schemas['MemorySummary']
export type MemoryOut = Schemas['MemoryOut']

export type ConnectionCheckOut = Schemas['ConnectionCheckOut']
export type ConnectionsTestOut = Schemas['ConnectionsTestOut']
export type AdminModelOut = Schemas['AdminModelOut']
export type AdminTaskModelsOut = Schemas['AdminTaskModelsOut']
export type AdminModelsOut = Schemas['AdminModelsOut']

export type QualityReviewIn = Schemas['QualityReviewIn']
export type QualityReviewOut = Schemas['QualityReviewOut']
export type QualityReviewSummary = Schemas['QualityReviewSummary']
export type QualityReport = Schemas['QualityReport']
export type QualityFinding = Schemas['QualityFinding']
export type InvestCheck = Schemas['InvestCheck']
export type SourceRef = Schemas['SourceRef']
// Editar a mano (RF-32): el contenido completo editado (HU o suite), la huella mostrada y una nota opcional.
export type EditIn = Schemas['EditIn']
