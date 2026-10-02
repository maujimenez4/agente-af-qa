// GENERADO desde docs/api/openapi.yaml con openapi-typescript: no editar a mano.
// Regenerar con: npm run api:types (y comprobar con npm run api:check).
export interface paths {
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Iniciar sesión
         * @description Crea la cookie de sesión HttpOnly y devuelve el usuario y el token anti-CSRF.
         */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cerrar sesión */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sesión actual
         * @description Al recargar la página: usuario y el token anti-CSRF de la sesión.
         */
        get: operations["me_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Conversaciones de la persona (más recientes primero) */
        get: operations["list_conversations_api_v1_conversations_get"];
        put?: never;
        /**
         * Crear una conversación y empezar a generar
         * @description Responde 202 con `state=generating`; el avance llega por `/events` o consultando la conversación. El `id` lo genera el servidor.
         */
        post: operations["create_conversation_api_v1_conversations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Estado completo de una conversación
         * @description Progreso, propuesta en revisión (con `plan`, `fingerprint` y `error`), versiones y resultado. Sirve también para retomarla.
         */
        get: operations["get_conversation_api_v1_conversations__conversation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Aprobar y publicar (simulación o real)
         * @description Con la `fingerprint` exacta del último payload. Si no casa, la revisión sigue con `review.error`. Un rechazo del registro de aprobaciones da 409 `approval_rejected` y obliga a empezar de nuevo; si la conversación no está en revisión o ya hay una operación en curso, 409 `not_in_review` (como en `iterate`).
         */
        post: operations["approve_api_v1_conversations__conversation_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/discard": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Descartar la propuesta */
        post: operations["discard_api_v1_conversations__conversation_id__discard_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/edit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Editar a mano (RF-32): versión nueva con su huella
         * @description `fingerprint` es la del payload mostrado. Una edición inválida no da error HTTP: la revisión sigue con `review.error` (UI.md §5).
         */
        post: operations["edit_api_v1_conversations__conversation_id__edit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Eventos en vivo (SSE)
         * @description `text/event-stream`. Eventos: `progress` (`data`: un `ProgressStep` completo), `review_ready`, `result` (publicación simulada, real o parcial, o descarte) y `error` (`data`: la conversación completa, como en `GET /conversations/{id}`). El servidor cierra el flujo tras `result` de una conversación terminada: ciérralo también en el cliente para que `EventSource` no reconecte. Hay un comentario `: ping` cada 15 s. Si se corta, basta con consultar el estado.
         */
        get: operations["events_api_v1_conversations__conversation_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/handoff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pasar la HU aprobada a QA (provisional, T-54) */
        post: operations["handoff_api_v1_conversations__conversation_id__handoff_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/iterate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pedir un cambio (RF-20) */
        post: operations["iterate_api_v1_conversations__conversation_id__iterate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/epics/{key}/stories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** HU de una épica */
        get: operations["list_children_api_v1_epics__key__stories_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/issues/{key}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ficha de una incidencia (tarjetas de HU parecida o clave reconocida) */
        get: operations["issue_card_api_v1_issues__key__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Proyectos que ve la conexión y el preseleccionado (T-50) */
        get: operations["list_projects_api_v1_projects_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project}/epics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Épicas del proyecto (Elegir en Jira) */
        get: operations["list_epics_api_v1_projects__project__epics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project}/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Buscar HU y épicas por texto o clave; sin `q`, las recientes del proyecto */
        get: operations["search_api_v1_projects__project__search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/choose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Fijar el proyecto de la conversación y recordarlo como último usado */
        post: operations["choose_project_api_v1_projects_choose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/qa/handoffs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** HU aprobadas listas para preparar pruebas (rol QA) */
        get: operations["list_handoffs_api_v1_qa_handoffs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/qa/handoffs/{handoff_id}/take": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recoger una HU y empezar su conversación de QA */
        post: operations["take_handoff_api_v1_qa_handoffs__handoff_id__take_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quality-reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revisar la calidad de una HU (T-48, no publica)
         * @description Responde 202 con `state=running`. Una HU que no existe o un límite del LLM llegan después en `state=error` con `error` (consultando la revisión).
         */
        post: operations["create_quality_review_api_v1_quality_reviews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quality-reviews/{review_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Estado e informe de una revisión de calidad
         * @description `report` se pinta campo a campo como texto; `report_markdown` es solo para descargarlo.
         */
        get: operations["get_quality_review_api_v1_quality_reviews__review_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Modo de publicación y modelos por tarea */
        get: operations["get_settings_api_v1_settings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings/models/{task}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Cambiar el modelo de una tarea en la sesión (RF-42) */
        put: operations["override_model_api_v1_settings_models__task__put"];
        post?: never;
        /** Volver a «Modelo automático» en una tarea (quita el cambio de la sesión) */
        delete: operations["clear_model_override_api_v1_settings_models__task__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings/usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Consumo de tokens de hoy (anillo del carril, PA-305)
         * @description Consumo de toda la instalación: el registro de uso no guarda la persona.
         */
        get: operations["usage_today_api_v1_settings_usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/start/propose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Proponer con qué empezar a partir del texto (sin IA, T-53)
         * @description Claves de Jira en el texto (también en minúsculas, si existen) o HU parecidas. Si `project_changed`, avisar; si `ignored_projects` no está vacío, avisar también.
         */
        post: operations["propose_api_v1_start_propose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/start/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Fuentes que usaría la propuesta (panel «Antes de generar»)
         * @description Las desmarcadas van en `excluded_sources` al crear la conversación; la fila `required` (la incidencia de origen) no se puede desmarcar.
         */
        post: operations["sources_api_v1_start_sources_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AcceptanceCriterion
         * @description Criterio de aceptación en Gherkin (RF-16).
         */
        AcceptanceCriterion: {
            /** Given */
            given: string[];
            /** Id */
            id: string;
            /** Then */
            then: string[];
            /** Title */
            title: string;
            /** When */
            when: string[];
        };
        /** ApproveIn */
        ApproveIn: {
            /** Fingerprint */
            fingerprint: string;
        };
        /** Artifact */
        Artifact: {
            /** Content */
            content: components["schemas"]["UserStory"] | components["schemas"]["TestSuite"];
            /** Created By */
            created_by: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            impact?: components["schemas"]["ImpactAnalysis"] | null;
            /** Model Used */
            model_used?: string | null;
            /** Origin Key */
            origin_key: string | null;
            /** Prompt Version */
            prompt_version?: string | null;
            status: components["schemas"]["ArtifactStatus"];
            type: components["schemas"]["ArtifactType"];
            /** Version */
            version: number;
        };
        /**
         * ArtifactStatus
         * @enum {string}
         */
        ArtifactStatus: "draft" | "in_review" | "approved" | "published" | "discarded";
        /**
         * ArtifactType
         * @enum {string}
         */
        ArtifactType: "user_story" | "test_suite";
        /**
         * BusinessRule
         * @description Regla de negocio identificada (RF-17).
         */
        BusinessRule: {
            /** Description */
            description: string;
            /** Id */
            id: string;
        };
        /** ChooseProjectIn */
        ChooseProjectIn: {
            /** Project */
            project: string;
        };
        /** ChooseProjectOut */
        ChooseProjectOut: {
            /** Project */
            project: string;
        };
        /** ConversationCreateIn */
        ConversationCreateIn: {
            /**
             * Excluded Sources
             * @default []
             */
            excluded_sources: string[];
            /**
             * Feedback
             * @description Restricciones, tipos de caso o `evolve_feedback` de T-48 (uno por hallazgo).
             * @default []
             */
            feedback: string[];
            /**
             * Flow
             * @enum {string}
             */
            flow: "need" | "evolve" | "tests";
            origin: components["schemas"]["OriginIn"];
        };
        /**
         * ConversationOut
         * @description Detalle de una conversación.
         *
         *     `state` amplía el `status` de la lista (`ConversationSummary`): `generating` cuando el grafo
         *     está trabajando (en la lista, `started` o el estado anterior) y `error` cuando la última
         *     operación falló. Una publicación parcial queda en `approved` con `result.errors`.
         */
        ConversationOut: {
            error?: components["schemas"]["ErrorBody"] | null;
            /**
             * Feedback
             * @default []
             */
            feedback: string[];
            /**
             * Flow
             * @enum {string}
             */
            flow: "need" | "evolve" | "tests";
            /**
             * Id
             * @description Identificador de la conversación (generado por el servidor).
             */
            id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "functional" | "qa";
            /** Progress */
            progress: components["schemas"]["ProgressStep"][];
            /** Project */
            project: string;
            result?: components["schemas"]["PublishOutcome"] | null;
            review?: components["schemas"]["ReviewPayload"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "generating" | "in_review" | "approved" | "simulated" | "published" | "discarded" | "error";
            /** Title */
            title: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Versions
             * @default []
             */
            versions: components["schemas"]["VersionOut"][];
        };
        /**
         * ConversationSummary
         * @description Una fila de la lista de conversaciones (UI.md, marco común).
         */
        ConversationSummary: {
            /** Artifact Id */
            artifact_id?: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "functional" | "qa";
            /** Origin Key */
            origin_key?: string | null;
            /**
             * Origin Kind
             * @enum {string}
             */
            origin_kind: "epic" | "story" | "need";
            /** Project Key */
            project_key: string;
            /**
             * Status
             * @enum {string}
             */
            status: "started" | "in_review" | "approved" | "published" | "simulated" | "discarded";
            /** Thread Id */
            thread_id: string;
            /** Title */
            title: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Username */
            username: string;
            /** Version */
            version?: number | null;
        };
        /** EditIn */
        EditIn: {
            /**
             * Content
             * @description Contenido completo editado: HU o suite, según el artefacto en revisión.
             */
            content: components["schemas"]["UserStory"] | components["schemas"]["TestSuite"];
            /**
             * Feedback
             * @description Nota opcional (RF-20).
             */
            feedback?: string | null;
            /** Fingerprint */
            fingerprint: string;
        };
        /** ErrorBody */
        ErrorBody: {
            /**
             * Code
             * @description Código estable para la UI. `message` ya está en español y listo para mostrar.
             * @enum {string}
             */
            code: "unauthenticated" | "invalid_credentials" | "too_many_attempts" | "forbidden" | "invalid_request" | "payload_too_large" | "not_found" | "project_not_found" | "method_not_allowed" | "http_error" | "not_in_review" | "approval_rejected" | "operation_failed" | "restart" | "too_many_streams" | "rate_limited" | "service_unavailable" | "provider_timeout" | "invalid_model_output" | "citation_failed" | "coverage_failed" | "quality_failed" | "publish_failed" | "not_implemented" | "unexpected";
            /**
             * Message
             * @description Mensaje en español para mostrar a la persona.
             */
            message: string;
            /**
             * Retry After
             * @description Segundos a esperar antes de reintentar, si aplica.
             */
            retry_after?: number | null;
        };
        /** ErrorResponse */
        ErrorResponse: {
            error: components["schemas"]["ErrorBody"];
        };
        /** HandoffOut */
        HandoffOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** From User */
            from_user: string;
            /** Id */
            id: string;
            /** Project */
            project: string;
            /**
             * Story Key
             * @description Sin clave si la HU solo se aprobó en simulación.
             */
            story_key: string | null;
            /** Title */
            title: string;
            /** Version */
            version: number;
        };
        /** ImpactAnalysis */
        ImpactAnalysis: {
            /** Affected */
            affected: components["schemas"]["ImpactItem"][];
            /** Diffs */
            diffs: components["schemas"]["StoryDiff"][];
            /** Regression Notes */
            regression_notes: string[];
        };
        /** ImpactItem */
        ImpactItem: {
            /** Jira Key */
            jira_key: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "story" | "rule" | "dependency" | "regression";
            /** Reason */
            reason: string;
        };
        /** InvestCheck */
        InvestCheck: {
            /**
             * Letter
             * @enum {string}
             */
            letter: "I" | "N" | "V" | "E" | "S" | "T";
            /** Reason */
            reason: string;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "ok" | "improvable";
        };
        /**
         * IssueCard
         * @description Ficha de una incidencia para las tarjetas (HU parecida, clave reconocida).
         */
        IssueCard: {
            /**
             * Criteria Count
             * @description CA contados en la descripción, sin IA.
             */
            criteria_count: number;
            /** Epic Key */
            epic_key?: string | null;
            /** Issue Type */
            issue_type: string;
            /** Key */
            key: string;
            /** Project */
            project: string;
            /**
             * Rules Count
             * @description RN contadas en la descripción, sin IA.
             */
            rules_count: number;
            /** Status */
            status: string;
            /** Summary */
            summary: string;
        };
        /** IssueSummary */
        IssueSummary: {
            /** Issue Type */
            issue_type: string;
            /** Key */
            key: string;
            /** Status */
            status: string;
            /** Summary */
            summary: string;
        };
        /** IterateIn */
        IterateIn: {
            /** Feedback */
            feedback: string;
        };
        /** LoginIn */
        LoginIn: {
            /** Password */
            password: string;
            /** Username */
            username: string;
        };
        /** ModelChoiceOut */
        ModelChoiceOut: {
            /** Model */
            model: string;
            /** Provider */
            provider: string;
        };
        /** ModelOverrideIn */
        ModelOverrideIn: {
            /** Model */
            model: string;
            /** Provider */
            provider: string;
        };
        /** Origin */
        Origin: {
            /** Key */
            key?: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "epic" | "story" | "need";
            /** Project */
            project?: string;
            /** Text */
            text?: string;
        };
        /** OriginIn */
        OriginIn: {
            /** Key */
            key?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "epic" | "story" | "need";
            /** Project */
            project: string;
            /** Text */
            text?: string | null;
        };
        /**
         * Priority
         * @enum {string}
         */
        Priority: "Must" | "Should" | "Could" | "Won't";
        /** ProgressStep */
        ProgressStep: {
            /** Label */
            label: string;
            /**
             * Node
             * @enum {string}
             */
            node: "load_origin" | "retrieve_context" | "generate" | "publish" | "memorize";
            /**
             * State
             * @enum {string}
             */
            state: "pending" | "running" | "done";
        };
        /** ProjectsOut */
        ProjectsOut: {
            /**
             * Preselected
             * @description Último proyecto usado o, si no, `JIRA_PROJECT_KEY` si es visible (T-50).
             */
            preselected: string | null;
            /** Projects */
            projects: components["schemas"]["ProjectSummary"][];
        };
        /** ProjectSummary */
        ProjectSummary: {
            /** Key */
            key: string;
            /** Name */
            name: string;
        };
        /** ProposeIn */
        ProposeIn: {
            /**
             * Mode
             * @default functional
             * @enum {string}
             */
            mode: "functional" | "qa";
            /** Project */
            project: string;
            /** Text */
            text: string;
        };
        /** PublishOutcome */
        PublishOutcome: {
            /**
             * Approved At
             * Format: date-time
             */
            approved_at: string;
            /** Approved By */
            approved_by: string;
            /**
             * Errors
             * @description Publicación parcial (RNF-13).
             * @default []
             */
            errors: string[];
            /**
             * Failed Ids
             * @description CP o adjuntos que fallaron (para «Reintentar solo los fallidos»).
             * @default []
             */
            failed_ids: string[];
            /** Plan */
            plan: {
                [key: string]: string;
            }[];
            /**
             * Published Keys
             * @default []
             */
            published_keys: string[];
            /** Simulated */
            simulated: boolean;
        };
        /** QualityFinding */
        QualityFinding: {
            /** Explanation */
            explanation: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "ambiguity" | "gap" | "no_source" | "invest" | "inconsistency";
            /** Proposal */
            proposal: string;
            /** Target Id */
            target_id?: string | null;
        };
        /** QualityReport */
        QualityReport: {
            /** Findings */
            findings: components["schemas"]["QualityFinding"][];
            /** Invest */
            invest: components["schemas"]["InvestCheck"][];
            /**
             * Open Questions
             * @default []
             */
            open_questions: string[];
            /**
             * Sources
             * @default []
             */
            sources: components["schemas"]["SourceRef"][];
            /** Summary */
            summary: string;
        };
        /** QualityReviewIn */
        QualityReviewIn: {
            /**
             * Excluded Sources
             * @default []
             */
            excluded_sources: string[];
            /** Issue Key */
            issue_key: string;
        };
        /** QualityReviewOut */
        QualityReviewOut: {
            error?: components["schemas"]["ErrorBody"] | null;
            /**
             * Evolve Feedback
             * @description Feedback inicial para «Evolucionar con esto».
             * @default []
             */
            evolve_feedback: string[];
            /** Id */
            id: string;
            /** Issue Key */
            issue_key: string;
            report?: components["schemas"]["QualityReport"] | null;
            /**
             * Report Markdown
             * @description Informe escapado, **solo para descargar** (no pintarlo).
             */
            report_markdown?: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "running" | "done" | "error";
        };
        /**
         * ReviewPayload
         * @description La pausa de `human_review` (UI.md §5, anexo §11 de la SPEC).
         */
        ReviewPayload: {
            artifact: components["schemas"]["Artifact"];
            /** Decisions */
            decisions: ("iterate" | "edit" | "approve" | "discard")[];
            /**
             * Error
             * @description Motivo de la última respuesta rechazada (la revisión sigue).
             */
            error?: string | null;
            /**
             * Fingerprint
             * @description Huella que hay que devolver **tal cual** para aprobar.
             */
            fingerprint: string;
            impact?: components["schemas"]["ImpactAnalysis"] | null;
            /**
             * Plan
             * @description Operaciones de Jira: el recibo (RF-31).
             */
            plan: {
                [key: string]: string;
            }[];
            /**
             * Target
             * @description Operación que se aprobará (`describe()`).
             */
            target: {
                [key: string]: string | null;
            };
            /** Version */
            version: number;
        };
        /** SessionOut */
        SessionOut: {
            /**
             * Csrf Token
             * @description Se envía en la cabecera `X-CSRF-Token` en toda petición que modifica algo. La sesión va en una cookie HttpOnly que el frontend no ve.
             */
            csrf_token: string;
            user: components["schemas"]["UserOut"];
        };
        /** SettingsOut */
        SettingsOut: {
            /**
             * Publish Mode
             * @enum {string}
             */
            publish_mode: "simulation" | "live";
            /** Tasks */
            tasks: components["schemas"]["TaskModelsOut"][];
        };
        /**
         * SourcePreview
         * @description Una fila del panel de fuentes; `ref` es lo que se pasa en `excluded_sources`.
         */
        SourcePreview: {
            /** Category */
            category?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "jira" | "rag" | "memory";
            /** Ref */
            ref: string;
            /**
             * Required
             * @default false
             */
            required: boolean;
            /** Title */
            title: string;
        };
        /**
         * SourceRef
         * @description Fuente citada por un artefacto (RF-21, RNF-14).
         */
        SourceRef: {
            /** Excerpt */
            excerpt?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "jira" | "rag" | "memory";
            /** Ref */
            ref: string;
        };
        /** SourcesIn */
        SourcesIn: {
            /**
             * Excluded Sources
             * @default []
             */
            excluded_sources: string[];
            origin: components["schemas"]["OriginIn"];
        };
        /**
         * StartOption
         * @description Una forma de empezar; `origin` va tal cual a `initial_state`.
         */
        StartOption: {
            issue?: components["schemas"]["IssueSummary"] | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "evolve" | "new_story_in_epic" | "tests" | "new_need";
            /** Label */
            label: string;
            origin: components["schemas"]["Origin"];
        };
        /** StartProposal */
        StartProposal: {
            /**
             * Ignored Projects
             * @default []
             */
            ignored_projects: string[];
            /** Options */
            options: components["schemas"]["StartOption"][];
            /** Project */
            project: string;
            /** Project Changed */
            project_changed: boolean;
            /** Recognized */
            recognized: components["schemas"]["IssueSummary"][];
            /** Similar */
            similar: components["schemas"]["IssueSummary"][];
        };
        /** StoryDiff */
        StoryDiff: {
            /** After */
            after: string | null;
            /** Before */
            before: string | null;
            /** Field */
            field: string;
        };
        /** TaskModelsOut */
        TaskModelsOut: {
            /** Chain */
            chain: components["schemas"]["ModelChoiceOut"][];
            override?: components["schemas"]["ModelChoiceOut"] | null;
            /** Task */
            task: string;
        };
        /**
         * TestCase
         * @description Caso de prueba trazable a CA y RN (RF-23).
         */
        TestCase: {
            /** Criterion Ids */
            criterion_ids: string[];
            /** Gherkin */
            gherkin?: string | null;
            /** Internal Id */
            internal_id: string;
            /** Preconditions */
            preconditions: string[];
            priority: components["schemas"]["Priority"];
            /**
             * Rule Ids
             * @default []
             */
            rule_ids: string[];
            /** Steps */
            steps: components["schemas"]["TestStep"][];
            /** Title */
            title: string;
            type: components["schemas"]["TestCaseType"];
        };
        /**
         * TestCaseType
         * @enum {string}
         */
        TestCaseType: "positivo" | "negativo" | "alterno" | "excepcion";
        /** TestStep */
        TestStep: {
            /** Action */
            action: string;
            /** Data */
            data?: string | null;
            /** Expected */
            expected: string;
        };
        /**
         * TestSuite
         * @description Artefactos de QA de una HU; se publica en Jira nativo (D-09).
         */
        TestSuite: {
            /** Cases */
            cases: components["schemas"]["TestCase"][];
            /**
             * Dependencies
             * @default []
             */
            dependencies: string[];
            /**
             * Impact Areas
             * @default []
             */
            impact_areas: string[];
            /**
             * Risks
             * @default []
             */
            risks: string[];
            /**
             * Sources
             * @default []
             */
            sources: components["schemas"]["SourceRef"][];
            /** Story Jira Key */
            story_jira_key: string;
            /** Strategy Md */
            strategy_md: string;
            /**
             * Synthetic Data
             * @default []
             */
            synthetic_data: {
                [key: string]: string;
            }[];
        };
        /**
         * UsageTodayOut
         * @description Consumo de tokens de hoy (PA-305), para el anillo del carril.
         */
        UsageTodayOut: {
            /**
             * Scope
             * @description El registro de uso no guarda la persona: el consumo es el de toda la instalación.
             * @default global
             * @constant
             */
            scope: "global";
            /**
             * Tokens Today
             * @description Tokens de todas las llamadas al LLM de hoy.
             */
            tokens_today: number;
            /**
             * Warning Threshold
             * @description Umbral de aviso diario (`limits.daily_token_warning`).
             */
            warning_threshold: number;
        };
        /** UserOut */
        UserOut: {
            /**
             * Permissions
             * @description Permisos de `core/permissions.py` del rol.
             */
            permissions: string[];
            /**
             * Role
             * @enum {string}
             */
            role: "functional" | "qa" | "admin";
            /** Username */
            username: string;
        };
        /**
         * UserStory
         * @description Plantilla completa de HU del proyecto (RF-15).
         */
        UserStory: {
            /** Acceptance Criteria */
            acceptance_criteria: components["schemas"]["AcceptanceCriterion"][];
            /** Action */
            action: string;
            /** Alternate Flows */
            alternate_flows: string[];
            /** Assumptions */
            assumptions: string[];
            /** Benefit */
            benefit: string;
            /** Business Goal */
            business_goal: string;
            /** Business Rules */
            business_rules: components["schemas"]["BusinessRule"][];
            /**
             * Changes From Previous
             * @default []
             */
            changes_from_previous: string[];
            /** Constraints */
            constraints: string[];
            /** Dependencies */
            dependencies: string[];
            /** Description */
            description: string;
            /** Exceptions */
            exceptions: string[];
            /** Internal Id */
            internal_id?: string | null;
            /** Jira Key */
            jira_key?: string | null;
            /**
             * Open Questions
             * @default []
             */
            open_questions: string[];
            priority: components["schemas"]["Priority"];
            /** Related Features */
            related_features: string[];
            /**
             * Related Requirements
             * @default []
             */
            related_requirements: string[];
            /** Role */
            role: string;
            /** Scope Excludes */
            scope_excludes: string[];
            /** Scope Includes */
            scope_includes: string[];
            /**
             * Sources
             * @default []
             */
            sources: components["schemas"]["SourceRef"][];
            /** Title */
            title: string;
        };
        /** VersionOut */
        VersionOut: {
            artifact: components["schemas"]["Artifact"];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Edited
             * @description Versión editada a mano (RF-32).
             * @default false
             */
            edited: boolean;
            /** Version */
            version: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "user": {
                     *         "username": "af-demo",
                     *         "role": "functional",
                     *         "permissions": [
                     *           "view_context",
                     *           "generate_story",
                     *           "publish_story",
                     *           "view_memory"
                     *         ]
                     *       },
                     *       "csrf_token": "csrf-token-ficticio-0123456789abcdef"
                     *     }
                     */
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Credenciales. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_credentials",
                     *         "message": "Usuario o contraseña incorrectos."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description `Origin`/`Referer` que no es el mismo origen ni está en la lista permitida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "La petición no viene de un origen permitido."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Intentos. */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "too_many_attempts",
                     *         "message": "Demasiados intentos; espera unos minutos."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    me_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "user": {
                     *         "username": "af-demo",
                     *         "role": "functional",
                     *         "permissions": [
                     *           "view_context",
                     *           "generate_story",
                     *           "publish_story",
                     *           "view_memory"
                     *         ]
                     *       },
                     *       "csrf_token": "csrf-token-ficticio-0123456789abcdef"
                     *     }
                     */
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_conversations_api_v1_conversations_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "thread_id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *         "username": "af-demo",
                     *         "project_key": "DEMO",
                     *         "mode": "functional",
                     *         "origin_kind": "story",
                     *         "origin_key": "DEMO-3",
                     *         "title": "Evolucionar DEMO-3",
                     *         "status": "in_review",
                     *         "artifact_id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *         "version": 2,
                     *         "created_at": "2026-10-02T10:30:00Z",
                     *         "updated_at": "2026-10-02T10:30:00Z"
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["ConversationSummary"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_conversation_api_v1_conversations_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConversationCreateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "generating",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "running"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "pending"
                     *         }
                     *       ],
                     *       "versions": [],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Proyecto que no ve la conexión de Jira, o incidencia de origen que no existe. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "El proyecto DEMO no existe o la conexión no tiene acceso a él."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_conversation_api_v1_conversations__conversation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "in_review",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "done"
                     *         }
                     *       ],
                     *       "review": {
                     *         "artifact": {
                     *           "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *           "type": "user_story",
                     *           "status": "in_review",
                     *           "version": 2,
                     *           "origin_key": "DEMO-3",
                     *           "content": {
                     *             "internal_id": "HU-02",
                     *             "jira_key": "DEMO-3",
                     *             "title": "Renovar un préstamo",
                     *             "role": "persona socia de la biblioteca",
                     *             "action": "renovar un préstamo activo desde la web o la app",
                     *             "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *             "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *             "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *             "scope_includes": [
                     *               "Renovación desde la ficha del préstamo",
                     *               "Renovación desde la app"
                     *             ],
                     *             "scope_excludes": [
                     *               "Renovación de materiales audiovisuales"
                     *             ],
                     *             "acceptance_criteria": [
                     *               {
                     *                 "id": "CA-01",
                     *                 "title": "Renovación permitida",
                     *                 "given": [
                     *                   "un préstamo activo con menos de 2 renovaciones",
                     *                   "sin reservas pendientes"
                     *                 ],
                     *                 "when": [
                     *                   "la persona socia pulsa «Renovar»"
                     *                 ],
                     *                 "then": [
                     *                   "el vencimiento se amplía 21 días"
                     *                 ]
                     *               },
                     *               {
                     *                 "id": "CA-02",
                     *                 "title": "Renovación rechazada por reservas",
                     *                 "given": [
                     *                   "un préstamo activo con reservas pendientes"
                     *                 ],
                     *                 "when": [
                     *                   "la persona socia pulsa «Renovar»"
                     *                 ],
                     *                 "then": [
                     *                   "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                 ]
                     *               }
                     *             ],
                     *             "business_rules": [
                     *               {
                     *                 "id": "RN-01",
                     *                 "description": "Máximo 2 renovaciones por préstamo."
                     *               },
                     *               {
                     *                 "id": "RN-02",
                     *                 "description": "No se renueva si hay reservas pendientes."
                     *               }
                     *             ],
                     *             "assumptions": [
                     *               "La persona socia ha iniciado sesión."
                     *             ],
                     *             "constraints": [
                     *               "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *             ],
                     *             "dependencies": [
                     *               "DEMO-2"
                     *             ],
                     *             "alternate_flows": [
                     *               "Renovación desde el correo de aviso de vencimiento."
                     *             ],
                     *             "exceptions": [
                     *               "El servicio de catálogo no responde."
                     *             ],
                     *             "related_features": [
                     *               "Reservas"
                     *             ],
                     *             "changes_from_previous": [
                     *               "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *             ],
                     *             "related_requirements": [],
                     *             "priority": "Must",
                     *             "sources": [
                     *               {
                     *                 "kind": "rag",
                     *                 "ref": "DOC-01",
                     *                 "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *               },
                     *               {
                     *                 "kind": "jira",
                     *                 "ref": "DEMO-3",
                     *                 "excerpt": "Renovar un préstamo"
                     *               }
                     *             ],
                     *             "open_questions": []
                     *           },
                     *           "impact": {
                     *             "diffs": [
                     *               {
                     *                 "field": "acceptance_criteria.CA-02",
                     *                 "after": "Renovación rechazada por reservas"
                     *               }
                     *             ],
                     *             "affected": [
                     *               {
                     *                 "jira_key": "DEMO-2",
                     *                 "reason": "Comparte la regla de reservas",
                     *                 "kind": "rule"
                     *               }
                     *             ],
                     *             "regression_notes": [
                     *               "Revisar el flujo de reservas."
                     *             ]
                     *           },
                     *           "created_by": "af-demo",
                     *           "model_used": "local/qwen3:4b-instruct",
                     *           "prompt_version": "2"
                     *         },
                     *         "version": 2,
                     *         "target": {
                     *           "operation": "actualizar HU",
                     *           "project": "DEMO",
                     *           "jira_key": "DEMO-3"
                     *         },
                     *         "fingerprint": "4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f",
                     *         "impact": {
                     *           "diffs": [
                     *             {
                     *               "field": "acceptance_criteria.CA-02",
                     *               "after": "Renovación rechazada por reservas"
                     *             }
                     *           ],
                     *           "affected": [
                     *             {
                     *               "jira_key": "DEMO-2",
                     *               "reason": "Comparte la regla de reservas",
                     *               "kind": "rule"
                     *             }
                     *           ],
                     *           "regression_notes": [
                     *             "Revisar el flujo de reservas."
                     *           ]
                     *         },
                     *         "plan": [
                     *           {
                     *             "op": "update_story",
                     *             "project": "DEMO",
                     *             "key": "DEMO-3"
                     *           },
                     *           {
                     *             "op": "link",
                     *             "from": "DEMO-3",
                     *             "to": "DEMO-2",
                     *             "type": "relates to"
                     *           }
                     *         ],
                     *         "decisions": [
                     *           "iterate",
                     *           "edit",
                     *           "approve",
                     *           "discard"
                     *         ]
                     *       },
                     *       "versions": [
                     *         {
                     *           "version": 2,
                     *           "artifact": {
                     *             "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *             "type": "user_story",
                     *             "status": "in_review",
                     *             "version": 2,
                     *             "origin_key": "DEMO-3",
                     *             "content": {
                     *               "internal_id": "HU-02",
                     *               "jira_key": "DEMO-3",
                     *               "title": "Renovar un préstamo",
                     *               "role": "persona socia de la biblioteca",
                     *               "action": "renovar un préstamo activo desde la web o la app",
                     *               "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *               "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *               "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *               "scope_includes": [
                     *                 "Renovación desde la ficha del préstamo",
                     *                 "Renovación desde la app"
                     *               ],
                     *               "scope_excludes": [
                     *                 "Renovación de materiales audiovisuales"
                     *               ],
                     *               "acceptance_criteria": [
                     *                 {
                     *                   "id": "CA-01",
                     *                   "title": "Renovación permitida",
                     *                   "given": [
                     *                     "un préstamo activo con menos de 2 renovaciones",
                     *                     "sin reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "el vencimiento se amplía 21 días"
                     *                   ]
                     *                 },
                     *                 {
                     *                   "id": "CA-02",
                     *                   "title": "Renovación rechazada por reservas",
                     *                   "given": [
                     *                     "un préstamo activo con reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                   ]
                     *                 }
                     *               ],
                     *               "business_rules": [
                     *                 {
                     *                   "id": "RN-01",
                     *                   "description": "Máximo 2 renovaciones por préstamo."
                     *                 },
                     *                 {
                     *                   "id": "RN-02",
                     *                   "description": "No se renueva si hay reservas pendientes."
                     *                 }
                     *               ],
                     *               "assumptions": [
                     *                 "La persona socia ha iniciado sesión."
                     *               ],
                     *               "constraints": [
                     *                 "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *               ],
                     *               "dependencies": [
                     *                 "DEMO-2"
                     *               ],
                     *               "alternate_flows": [
                     *                 "Renovación desde el correo de aviso de vencimiento."
                     *               ],
                     *               "exceptions": [
                     *                 "El servicio de catálogo no responde."
                     *               ],
                     *               "related_features": [
                     *                 "Reservas"
                     *               ],
                     *               "changes_from_previous": [
                     *                 "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *               ],
                     *               "related_requirements": [],
                     *               "priority": "Must",
                     *               "sources": [
                     *                 {
                     *                   "kind": "rag",
                     *                   "ref": "DOC-01",
                     *                   "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *                 },
                     *                 {
                     *                   "kind": "jira",
                     *                   "ref": "DEMO-3",
                     *                   "excerpt": "Renovar un préstamo"
                     *                 }
                     *               ],
                     *               "open_questions": []
                     *             },
                     *             "impact": {
                     *               "diffs": [
                     *                 {
                     *                   "field": "acceptance_criteria.CA-02",
                     *                   "after": "Renovación rechazada por reservas"
                     *                 }
                     *               ],
                     *               "affected": [
                     *                 {
                     *                   "jira_key": "DEMO-2",
                     *                   "reason": "Comparte la regla de reservas",
                     *                   "kind": "rule"
                     *                 }
                     *               ],
                     *               "regression_notes": [
                     *                 "Revisar el flujo de reservas."
                     *               ]
                     *             },
                     *             "created_by": "af-demo",
                     *             "model_used": "local/qwen3:4b-instruct",
                     *             "prompt_version": "2"
                     *           },
                     *           "created_at": "2026-10-02T10:30:00Z",
                     *           "edited": false
                     *         }
                     *       ],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    approve_api_v1_conversations__conversation_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApproveIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "simulated",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "done"
                     *         }
                     *       ],
                     *       "versions": [
                     *         {
                     *           "version": 2,
                     *           "artifact": {
                     *             "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *             "type": "user_story",
                     *             "status": "in_review",
                     *             "version": 2,
                     *             "origin_key": "DEMO-3",
                     *             "content": {
                     *               "internal_id": "HU-02",
                     *               "jira_key": "DEMO-3",
                     *               "title": "Renovar un préstamo",
                     *               "role": "persona socia de la biblioteca",
                     *               "action": "renovar un préstamo activo desde la web o la app",
                     *               "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *               "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *               "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *               "scope_includes": [
                     *                 "Renovación desde la ficha del préstamo",
                     *                 "Renovación desde la app"
                     *               ],
                     *               "scope_excludes": [
                     *                 "Renovación de materiales audiovisuales"
                     *               ],
                     *               "acceptance_criteria": [
                     *                 {
                     *                   "id": "CA-01",
                     *                   "title": "Renovación permitida",
                     *                   "given": [
                     *                     "un préstamo activo con menos de 2 renovaciones",
                     *                     "sin reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "el vencimiento se amplía 21 días"
                     *                   ]
                     *                 },
                     *                 {
                     *                   "id": "CA-02",
                     *                   "title": "Renovación rechazada por reservas",
                     *                   "given": [
                     *                     "un préstamo activo con reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                   ]
                     *                 }
                     *               ],
                     *               "business_rules": [
                     *                 {
                     *                   "id": "RN-01",
                     *                   "description": "Máximo 2 renovaciones por préstamo."
                     *                 },
                     *                 {
                     *                   "id": "RN-02",
                     *                   "description": "No se renueva si hay reservas pendientes."
                     *                 }
                     *               ],
                     *               "assumptions": [
                     *                 "La persona socia ha iniciado sesión."
                     *               ],
                     *               "constraints": [
                     *                 "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *               ],
                     *               "dependencies": [
                     *                 "DEMO-2"
                     *               ],
                     *               "alternate_flows": [
                     *                 "Renovación desde el correo de aviso de vencimiento."
                     *               ],
                     *               "exceptions": [
                     *                 "El servicio de catálogo no responde."
                     *               ],
                     *               "related_features": [
                     *                 "Reservas"
                     *               ],
                     *               "changes_from_previous": [
                     *                 "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *               ],
                     *               "related_requirements": [],
                     *               "priority": "Must",
                     *               "sources": [
                     *                 {
                     *                   "kind": "rag",
                     *                   "ref": "DOC-01",
                     *                   "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *                 },
                     *                 {
                     *                   "kind": "jira",
                     *                   "ref": "DEMO-3",
                     *                   "excerpt": "Renovar un préstamo"
                     *                 }
                     *               ],
                     *               "open_questions": []
                     *             },
                     *             "impact": {
                     *               "diffs": [
                     *                 {
                     *                   "field": "acceptance_criteria.CA-02",
                     *                   "after": "Renovación rechazada por reservas"
                     *                 }
                     *               ],
                     *               "affected": [
                     *                 {
                     *                   "jira_key": "DEMO-2",
                     *                   "reason": "Comparte la regla de reservas",
                     *                   "kind": "rule"
                     *                 }
                     *               ],
                     *               "regression_notes": [
                     *                 "Revisar el flujo de reservas."
                     *               ]
                     *             },
                     *             "created_by": "af-demo",
                     *             "model_used": "local/qwen3:4b-instruct",
                     *             "prompt_version": "2"
                     *           },
                     *           "created_at": "2026-10-02T10:30:00Z",
                     *           "edited": false
                     *         }
                     *       ],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "result": {
                     *         "simulated": true,
                     *         "plan": [
                     *           {
                     *             "op": "update_story",
                     *             "project": "DEMO",
                     *             "key": "DEMO-3"
                     *           },
                     *           {
                     *             "op": "link",
                     *             "from": "DEMO-3",
                     *             "to": "DEMO-2",
                     *             "type": "relates to"
                     *           }
                     *         ],
                     *         "approved_by": "af-demo",
                     *         "approved_at": "2026-10-02T10:30:00Z",
                     *         "published_keys": [],
                     *         "errors": [],
                     *         "failed_ids": []
                     *       },
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Rechazo del registro de aprobaciones: la conversación no se recupera. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "approval_rejected",
                     *         "message": "La aprobación no corresponde a la versión revisada; empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    discard_api_v1_conversations__conversation_id__discard_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "discarded",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "done"
                     *         }
                     *       ],
                     *       "versions": [
                     *         {
                     *           "version": 2,
                     *           "artifact": {
                     *             "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *             "type": "user_story",
                     *             "status": "in_review",
                     *             "version": 2,
                     *             "origin_key": "DEMO-3",
                     *             "content": {
                     *               "internal_id": "HU-02",
                     *               "jira_key": "DEMO-3",
                     *               "title": "Renovar un préstamo",
                     *               "role": "persona socia de la biblioteca",
                     *               "action": "renovar un préstamo activo desde la web o la app",
                     *               "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *               "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *               "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *               "scope_includes": [
                     *                 "Renovación desde la ficha del préstamo",
                     *                 "Renovación desde la app"
                     *               ],
                     *               "scope_excludes": [
                     *                 "Renovación de materiales audiovisuales"
                     *               ],
                     *               "acceptance_criteria": [
                     *                 {
                     *                   "id": "CA-01",
                     *                   "title": "Renovación permitida",
                     *                   "given": [
                     *                     "un préstamo activo con menos de 2 renovaciones",
                     *                     "sin reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "el vencimiento se amplía 21 días"
                     *                   ]
                     *                 },
                     *                 {
                     *                   "id": "CA-02",
                     *                   "title": "Renovación rechazada por reservas",
                     *                   "given": [
                     *                     "un préstamo activo con reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                   ]
                     *                 }
                     *               ],
                     *               "business_rules": [
                     *                 {
                     *                   "id": "RN-01",
                     *                   "description": "Máximo 2 renovaciones por préstamo."
                     *                 },
                     *                 {
                     *                   "id": "RN-02",
                     *                   "description": "No se renueva si hay reservas pendientes."
                     *                 }
                     *               ],
                     *               "assumptions": [
                     *                 "La persona socia ha iniciado sesión."
                     *               ],
                     *               "constraints": [
                     *                 "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *               ],
                     *               "dependencies": [
                     *                 "DEMO-2"
                     *               ],
                     *               "alternate_flows": [
                     *                 "Renovación desde el correo de aviso de vencimiento."
                     *               ],
                     *               "exceptions": [
                     *                 "El servicio de catálogo no responde."
                     *               ],
                     *               "related_features": [
                     *                 "Reservas"
                     *               ],
                     *               "changes_from_previous": [
                     *                 "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *               ],
                     *               "related_requirements": [],
                     *               "priority": "Must",
                     *               "sources": [
                     *                 {
                     *                   "kind": "rag",
                     *                   "ref": "DOC-01",
                     *                   "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *                 },
                     *                 {
                     *                   "kind": "jira",
                     *                   "ref": "DEMO-3",
                     *                   "excerpt": "Renovar un préstamo"
                     *                 }
                     *               ],
                     *               "open_questions": []
                     *             },
                     *             "impact": {
                     *               "diffs": [
                     *                 {
                     *                   "field": "acceptance_criteria.CA-02",
                     *                   "after": "Renovación rechazada por reservas"
                     *                 }
                     *               ],
                     *               "affected": [
                     *                 {
                     *                   "jira_key": "DEMO-2",
                     *                   "reason": "Comparte la regla de reservas",
                     *                   "kind": "rule"
                     *                 }
                     *               ],
                     *               "regression_notes": [
                     *                 "Revisar el flujo de reservas."
                     *               ]
                     *             },
                     *             "created_by": "af-demo",
                     *             "model_used": "local/qwen3:4b-instruct",
                     *             "prompt_version": "2"
                     *           },
                     *           "created_at": "2026-10-02T10:30:00Z",
                     *           "edited": false
                     *         }
                     *       ],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Estado que no admite la operación. También «Demasiadas respuestas rechazadas…»: empieza una conversación nueva. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_in_review",
                     *         "message": "La conversación no tiene una propuesta en revisión (está generando o ya terminó)."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    edit_api_v1_conversations__conversation_id__edit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EditIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "in_review",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "done"
                     *         }
                     *       ],
                     *       "review": {
                     *         "artifact": {
                     *           "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *           "type": "user_story",
                     *           "status": "in_review",
                     *           "version": 2,
                     *           "origin_key": "DEMO-3",
                     *           "content": {
                     *             "internal_id": "HU-02",
                     *             "jira_key": "DEMO-3",
                     *             "title": "Renovar un préstamo",
                     *             "role": "persona socia de la biblioteca",
                     *             "action": "renovar un préstamo activo desde la web o la app",
                     *             "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *             "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *             "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *             "scope_includes": [
                     *               "Renovación desde la ficha del préstamo",
                     *               "Renovación desde la app"
                     *             ],
                     *             "scope_excludes": [
                     *               "Renovación de materiales audiovisuales"
                     *             ],
                     *             "acceptance_criteria": [
                     *               {
                     *                 "id": "CA-01",
                     *                 "title": "Renovación permitida",
                     *                 "given": [
                     *                   "un préstamo activo con menos de 2 renovaciones",
                     *                   "sin reservas pendientes"
                     *                 ],
                     *                 "when": [
                     *                   "la persona socia pulsa «Renovar»"
                     *                 ],
                     *                 "then": [
                     *                   "el vencimiento se amplía 21 días"
                     *                 ]
                     *               },
                     *               {
                     *                 "id": "CA-02",
                     *                 "title": "Renovación rechazada por reservas",
                     *                 "given": [
                     *                   "un préstamo activo con reservas pendientes"
                     *                 ],
                     *                 "when": [
                     *                   "la persona socia pulsa «Renovar»"
                     *                 ],
                     *                 "then": [
                     *                   "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                 ]
                     *               }
                     *             ],
                     *             "business_rules": [
                     *               {
                     *                 "id": "RN-01",
                     *                 "description": "Máximo 2 renovaciones por préstamo."
                     *               },
                     *               {
                     *                 "id": "RN-02",
                     *                 "description": "No se renueva si hay reservas pendientes."
                     *               }
                     *             ],
                     *             "assumptions": [
                     *               "La persona socia ha iniciado sesión."
                     *             ],
                     *             "constraints": [
                     *               "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *             ],
                     *             "dependencies": [
                     *               "DEMO-2"
                     *             ],
                     *             "alternate_flows": [
                     *               "Renovación desde el correo de aviso de vencimiento."
                     *             ],
                     *             "exceptions": [
                     *               "El servicio de catálogo no responde."
                     *             ],
                     *             "related_features": [
                     *               "Reservas"
                     *             ],
                     *             "changes_from_previous": [
                     *               "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *             ],
                     *             "related_requirements": [],
                     *             "priority": "Must",
                     *             "sources": [
                     *               {
                     *                 "kind": "rag",
                     *                 "ref": "DOC-01",
                     *                 "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *               },
                     *               {
                     *                 "kind": "jira",
                     *                 "ref": "DEMO-3",
                     *                 "excerpt": "Renovar un préstamo"
                     *               }
                     *             ],
                     *             "open_questions": []
                     *           },
                     *           "impact": {
                     *             "diffs": [
                     *               {
                     *                 "field": "acceptance_criteria.CA-02",
                     *                 "after": "Renovación rechazada por reservas"
                     *               }
                     *             ],
                     *             "affected": [
                     *               {
                     *                 "jira_key": "DEMO-2",
                     *                 "reason": "Comparte la regla de reservas",
                     *                 "kind": "rule"
                     *               }
                     *             ],
                     *             "regression_notes": [
                     *               "Revisar el flujo de reservas."
                     *             ]
                     *           },
                     *           "created_by": "af-demo",
                     *           "model_used": "local/qwen3:4b-instruct",
                     *           "prompt_version": "2"
                     *         },
                     *         "version": 2,
                     *         "target": {
                     *           "operation": "actualizar HU",
                     *           "project": "DEMO",
                     *           "jira_key": "DEMO-3"
                     *         },
                     *         "fingerprint": "4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f",
                     *         "impact": {
                     *           "diffs": [
                     *             {
                     *               "field": "acceptance_criteria.CA-02",
                     *               "after": "Renovación rechazada por reservas"
                     *             }
                     *           ],
                     *           "affected": [
                     *             {
                     *               "jira_key": "DEMO-2",
                     *               "reason": "Comparte la regla de reservas",
                     *               "kind": "rule"
                     *             }
                     *           ],
                     *           "regression_notes": [
                     *             "Revisar el flujo de reservas."
                     *           ]
                     *         },
                     *         "plan": [
                     *           {
                     *             "op": "update_story",
                     *             "project": "DEMO",
                     *             "key": "DEMO-3"
                     *           },
                     *           {
                     *             "op": "link",
                     *             "from": "DEMO-3",
                     *             "to": "DEMO-2",
                     *             "type": "relates to"
                     *           }
                     *         ],
                     *         "decisions": [
                     *           "iterate",
                     *           "edit",
                     *           "approve",
                     *           "discard"
                     *         ]
                     *       },
                     *       "versions": [
                     *         {
                     *           "version": 2,
                     *           "artifact": {
                     *             "id": "6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03",
                     *             "type": "user_story",
                     *             "status": "in_review",
                     *             "version": 2,
                     *             "origin_key": "DEMO-3",
                     *             "content": {
                     *               "internal_id": "HU-02",
                     *               "jira_key": "DEMO-3",
                     *               "title": "Renovar un préstamo",
                     *               "role": "persona socia de la biblioteca",
                     *               "action": "renovar un préstamo activo desde la web o la app",
                     *               "benefit": "no tener que acudir al mostrador para ampliar el plazo",
                     *               "description": "La persona socia renueva un préstamo activo antes de su vencimiento.",
                     *               "business_goal": "Reducir las visitas al mostrador por renovaciones.",
                     *               "scope_includes": [
                     *                 "Renovación desde la ficha del préstamo",
                     *                 "Renovación desde la app"
                     *               ],
                     *               "scope_excludes": [
                     *                 "Renovación de materiales audiovisuales"
                     *               ],
                     *               "acceptance_criteria": [
                     *                 {
                     *                   "id": "CA-01",
                     *                   "title": "Renovación permitida",
                     *                   "given": [
                     *                     "un préstamo activo con menos de 2 renovaciones",
                     *                     "sin reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "el vencimiento se amplía 21 días"
                     *                   ]
                     *                 },
                     *                 {
                     *                   "id": "CA-02",
                     *                   "title": "Renovación rechazada por reservas",
                     *                   "given": [
                     *                     "un préstamo activo con reservas pendientes"
                     *                   ],
                     *                   "when": [
                     *                     "la persona socia pulsa «Renovar»"
                     *                   ],
                     *                   "then": [
                     *                     "se muestra el aviso «El ejemplar tiene reservas pendientes»"
                     *                   ]
                     *                 }
                     *               ],
                     *               "business_rules": [
                     *                 {
                     *                   "id": "RN-01",
                     *                   "description": "Máximo 2 renovaciones por préstamo."
                     *                 },
                     *                 {
                     *                   "id": "RN-02",
                     *                   "description": "No se renueva si hay reservas pendientes."
                     *                 }
                     *               ],
                     *               "assumptions": [
                     *                 "La persona socia ha iniciado sesión."
                     *               ],
                     *               "constraints": [
                     *                 "Plazo de préstamo de 21 días (reglamento, art. 7)."
                     *               ],
                     *               "dependencies": [
                     *                 "DEMO-2"
                     *               ],
                     *               "alternate_flows": [
                     *                 "Renovación desde el correo de aviso de vencimiento."
                     *               ],
                     *               "exceptions": [
                     *                 "El servicio de catálogo no responde."
                     *               ],
                     *               "related_features": [
                     *                 "Reservas"
                     *               ],
                     *               "changes_from_previous": [
                     *                 "CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."
                     *               ],
                     *               "related_requirements": [],
                     *               "priority": "Must",
                     *               "sources": [
                     *                 {
                     *                   "kind": "rag",
                     *                   "ref": "DOC-01",
                     *                   "excerpt": "Cada préstamo admite hasta 2 renovaciones."
                     *                 },
                     *                 {
                     *                   "kind": "jira",
                     *                   "ref": "DEMO-3",
                     *                   "excerpt": "Renovar un préstamo"
                     *                 }
                     *               ],
                     *               "open_questions": []
                     *             },
                     *             "impact": {
                     *               "diffs": [
                     *                 {
                     *                   "field": "acceptance_criteria.CA-02",
                     *                   "after": "Renovación rechazada por reservas"
                     *                 }
                     *               ],
                     *               "affected": [
                     *                 {
                     *                   "jira_key": "DEMO-2",
                     *                   "reason": "Comparte la regla de reservas",
                     *                   "kind": "rule"
                     *                 }
                     *               ],
                     *               "regression_notes": [
                     *                 "Revisar el flujo de reservas."
                     *               ]
                     *             },
                     *             "created_by": "af-demo",
                     *             "model_used": "local/qwen3:4b-instruct",
                     *             "prompt_version": "2"
                     *           },
                     *           "created_at": "2026-10-02T10:30:00Z",
                     *           "edited": false
                     *         }
                     *       ],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Estado que no admite la operación. También «Demasiadas respuestas rechazadas…»: empieza una conversación nueva. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_in_review",
                     *         "message": "La conversación no tiene una propuesta en revisión (está generando o ya terminó)."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    events_api_v1_conversations__conversation_id__events_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example event: progress
                     *     data: {"node": "generate", "label": "Generar la propuesta, validar las citas y analizar el impacto", "state": "running"}
                     *
                     *     event: review_ready
                     *     data: {"id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d", "state": "in_review"}
                     */
                    "text/event-stream": unknown;
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de flujos SSE abiertos por persona (3). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "too_many_streams",
                     *         "message": "Tienes demasiadas pestañas siguiendo conversaciones."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    handoff_api_v1_conversations__conversation_id__handoff_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "c3e5a7b9-2d4f-4a6b-8c0d-1e2f3a4b5c6d",
                     *       "title": "Renovar un préstamo",
                     *       "project": "DEMO",
                     *       "story_key": "DEMO-3",
                     *       "version": 2,
                     *       "from_user": "af-demo",
                     *       "created_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["HandoffOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Pendiente del diseño de T-54 (PA-105). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_implemented",
                     *         "message": "Disponible cuando T-54 (QA encadenada) cierre su diseño."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    iterate_api_v1_conversations__conversation_id__iterate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Identificador de la conversación. */
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IterateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d",
                     *       "title": "Evolucionar DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "evolve",
                     *       "mode": "functional",
                     *       "state": "generating",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "running"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "pending"
                     *         }
                     *       ],
                     *       "versions": [],
                     *       "feedback": [
                     *         "Mismas reglas que en la web."
                     *       ],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Estado que no admite la operación. También «Demasiadas respuestas rechazadas…»: empieza una conversación nueva. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_in_review",
                     *         "message": "La conversación no tiene una propuesta en revisión (está generando o ya terminó)."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_children_api_v1_epics__key__stories_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "key": "DEMO-2",
                     *         "summary": "Reservar un libro",
                     *         "issue_type": "Story",
                     *         "status": "Hecho"
                     *       },
                     *       {
                     *         "key": "DEMO-3",
                     *         "summary": "Renovar un préstamo",
                     *         "issue_type": "Story",
                     *         "status": "Abierta"
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["IssueSummary"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    issue_card_api_v1_issues__key__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "key": "DEMO-3",
                     *       "project": "DEMO",
                     *       "summary": "Renovar un préstamo",
                     *       "issue_type": "Story",
                     *       "status": "Abierta",
                     *       "epic_key": "DEMO-1",
                     *       "criteria_count": 2,
                     *       "rules_count": 2
                     *     }
                     */
                    "application/json": components["schemas"]["IssueCard"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_projects_api_v1_projects_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "projects": [
                     *         {
                     *           "key": "DEMO",
                     *           "name": "Biblioteca"
                     *         },
                     *         {
                     *           "key": "SOCI",
                     *           "name": "Gestión de personas socias"
                     *         }
                     *       ],
                     *       "preselected": "DEMO"
                     *     }
                     */
                    "application/json": components["schemas"]["ProjectsOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_epics_api_v1_projects__project__epics_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "key": "DEMO-1",
                     *         "summary": "Préstamo digital",
                     *         "issue_type": "Epic",
                     *         "status": "Abierta"
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["IssueSummary"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    search_api_v1_projects__project__search_get: {
        parameters: {
            query?: {
                limit?: number;
                q?: string | null;
            };
            header?: never;
            path: {
                project: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "key": "DEMO-2",
                     *         "summary": "Reservar un libro",
                     *         "issue_type": "Story",
                     *         "status": "Hecho"
                     *       },
                     *       {
                     *         "key": "DEMO-3",
                     *         "summary": "Renovar un préstamo",
                     *         "issue_type": "Story",
                     *         "status": "Abierta"
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["IssueSummary"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    choose_project_api_v1_projects_choose_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChooseProjectIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "project": "DEMO"
                     *     }
                     */
                    "application/json": components["schemas"]["ChooseProjectOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Proyecto que no ve la conexión de Jira. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "project_not_found",
                     *         "message": "El proyecto DEMO no existe o la conexión no tiene acceso a él."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_handoffs_api_v1_qa_handoffs_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "id": "c3e5a7b9-2d4f-4a6b-8c0d-1e2f3a4b5c6d",
                     *         "title": "Renovar un préstamo",
                     *         "project": "DEMO",
                     *         "story_key": "DEMO-3",
                     *         "version": 2,
                     *         "from_user": "af-demo",
                     *         "created_at": "2026-10-02T10:30:00Z"
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["HandoffOut"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Pendiente del diseño de T-54 (PA-105). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_implemented",
                     *         "message": "Disponible cuando T-54 (QA encadenada) cierre su diseño."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    take_handoff_api_v1_qa_handoffs__handoff_id__take_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                handoff_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "d4f6b8c0-3e5a-4b7c-9d1e-2f3a4b5c6d7e",
                     *       "title": "Preparar pruebas de DEMO-3",
                     *       "project": "DEMO",
                     *       "flow": "tests",
                     *       "mode": "qa",
                     *       "state": "generating",
                     *       "progress": [
                     *         {
                     *           "node": "load_origin",
                     *           "label": "Cargar el origen",
                     *           "state": "done"
                     *         },
                     *         {
                     *           "node": "retrieve_context",
                     *           "label": "Recuperar contexto",
                     *           "state": "running"
                     *         },
                     *         {
                     *           "node": "generate",
                     *           "label": "Generar la propuesta",
                     *           "state": "pending"
                     *         }
                     *       ],
                     *       "versions": [],
                     *       "feedback": [],
                     *       "updated_at": "2026-10-02T10:30:00Z"
                     *     }
                     */
                    "application/json": components["schemas"]["ConversationOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Pendiente del diseño de T-54 (PA-105). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_implemented",
                     *         "message": "Disponible cuando T-54 (QA encadenada) cierre su diseño."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_quality_review_api_v1_quality_reviews_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QualityReviewIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "b2d4f6a8-1c3e-4f5a-8b9c-0d1e2f3a4b5c",
                     *       "issue_key": "DEMO-3",
                     *       "state": "done",
                     *       "report": {
                     *         "summary": "La HU es valiosa y pequeña; hay un criterio ambiguo y un hueco (ficticio).",
                     *         "invest": [
                     *           {
                     *             "letter": "I",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de I."
                     *           },
                     *           {
                     *             "letter": "N",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de N."
                     *           },
                     *           {
                     *             "letter": "V",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de V."
                     *           },
                     *           {
                     *             "letter": "E",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de E."
                     *           },
                     *           {
                     *             "letter": "S",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de S."
                     *           },
                     *           {
                     *             "letter": "T",
                     *             "verdict": "improvable",
                     *             "reason": "Motivo ficticio de T."
                     *           }
                     *         ],
                     *         "findings": [
                     *           {
                     *             "kind": "ambiguity",
                     *             "target_id": "CA-02",
                     *             "explanation": "«Avisar pronto» no se puede probar.",
                     *             "proposal": "Avisar en menos de 15 minutos."
                     *           },
                     *           {
                     *             "kind": "gap",
                     *             "explanation": "No dice qué pasa si la renovación falla.",
                     *             "proposal": "Añadir un criterio de error."
                     *           }
                     *         ],
                     *         "open_questions": [
                     *           "¿Hay un máximo de renovaciones por año? (ficticio)"
                     *         ],
                     *         "sources": [
                     *           {
                     *             "kind": "rag",
                     *             "ref": "DOC-01"
                     *           }
                     *         ]
                     *       },
                     *       "evolve_feedback": [
                     *         "CA-02: Avisar en menos de 15 minutos.",
                     *         "Añadir un criterio de error."
                     *       ],
                     *       "report_markdown": "# Calidad de DEMO-3\n\nLa HU es valiosa y pequeña; hay un criterio ambiguo y un hueco \\(ficticio\\).\n\n## INVEST\n\n- **I · Independiente**: Bien. Motivo ficticio de I.\n- **N · Negociable**: Bien. Motivo ficticio de N.\n- **V · Valiosa**: Bien. Motivo ficticio de V.\n- **E · Estimable**: Bien. Motivo ficticio de E.\n- **S · Pequeña**: Bien. Motivo ficticio de S.\n- **T · Testeable**: Mejorable. Motivo ficticio de T.\n\n## Hallazgos\n\n- **Ambigüedad · CA-02**: «Avisar pronto» no se puede probar. Propuesta: Avisar en menos de 15 minutos.\n- **Hueco**: No dice qué pasa si la renovación falla. Propuesta: Añadir un criterio de error.\n\n## Preguntas para negocio\n\n- ¿Hay un máximo de renovaciones por año? \\(ficticio\\)\n\n## Fuentes\n\n- DOC-01\n"
                     *     }
                     */
                    "application/json": components["schemas"]["QualityReviewOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_quality_review_api_v1_quality_reviews__review_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                review_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "id": "b2d4f6a8-1c3e-4f5a-8b9c-0d1e2f3a4b5c",
                     *       "issue_key": "DEMO-3",
                     *       "state": "done",
                     *       "report": {
                     *         "summary": "La HU es valiosa y pequeña; hay un criterio ambiguo y un hueco (ficticio).",
                     *         "invest": [
                     *           {
                     *             "letter": "I",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de I."
                     *           },
                     *           {
                     *             "letter": "N",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de N."
                     *           },
                     *           {
                     *             "letter": "V",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de V."
                     *           },
                     *           {
                     *             "letter": "E",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de E."
                     *           },
                     *           {
                     *             "letter": "S",
                     *             "verdict": "ok",
                     *             "reason": "Motivo ficticio de S."
                     *           },
                     *           {
                     *             "letter": "T",
                     *             "verdict": "improvable",
                     *             "reason": "Motivo ficticio de T."
                     *           }
                     *         ],
                     *         "findings": [
                     *           {
                     *             "kind": "ambiguity",
                     *             "target_id": "CA-02",
                     *             "explanation": "«Avisar pronto» no se puede probar.",
                     *             "proposal": "Avisar en menos de 15 minutos."
                     *           },
                     *           {
                     *             "kind": "gap",
                     *             "explanation": "No dice qué pasa si la renovación falla.",
                     *             "proposal": "Añadir un criterio de error."
                     *           }
                     *         ],
                     *         "open_questions": [
                     *           "¿Hay un máximo de renovaciones por año? (ficticio)"
                     *         ],
                     *         "sources": [
                     *           {
                     *             "kind": "rag",
                     *             "ref": "DOC-01"
                     *           }
                     *         ]
                     *       },
                     *       "evolve_feedback": [
                     *         "CA-02: Avisar en menos de 15 minutos.",
                     *         "Añadir un criterio de error."
                     *       ],
                     *       "report_markdown": "# Calidad de DEMO-3\n\nLa HU es valiosa y pequeña; hay un criterio ambiguo y un hueco \\(ficticio\\).\n\n## INVEST\n\n- **I · Independiente**: Bien. Motivo ficticio de I.\n- **N · Negociable**: Bien. Motivo ficticio de N.\n- **V · Valiosa**: Bien. Motivo ficticio de V.\n- **E · Estimable**: Bien. Motivo ficticio de E.\n- **S · Pequeña**: Bien. Motivo ficticio de S.\n- **T · Testeable**: Mejorable. Motivo ficticio de T.\n\n## Hallazgos\n\n- **Ambigüedad · CA-02**: «Avisar pronto» no se puede probar. Propuesta: Avisar en menos de 15 minutos.\n- **Hueco**: No dice qué pasa si la renovación falla. Propuesta: Añadir un criterio de error.\n\n## Preguntas para negocio\n\n- ¿Hay un máximo de renovaciones por año? \\(ficticio\\)\n\n## Fuentes\n\n- DOC-01\n"
                     *     }
                     */
                    "application/json": components["schemas"]["QualityReviewOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_settings_api_v1_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "publish_mode": "simulation",
                     *       "tasks": [
                     *         {
                     *           "task": "generate_story",
                     *           "chain": [
                     *             {
                     *               "provider": "local",
                     *               "model": "qwen3:4b-instruct"
                     *             }
                     *           ]
                     *         }
                     *       ]
                     *     }
                     */
                    "application/json": components["schemas"]["SettingsOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    override_model_api_v1_settings_models__task__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ModelOverrideIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "task": "generate_story",
                     *       "chain": [
                     *         {
                     *           "provider": "local",
                     *           "model": "qwen3:4b-instruct"
                     *         }
                     *       ]
                     *     }
                     */
                    "application/json": components["schemas"]["TaskModelsOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    clear_model_override_api_v1_settings_models__task__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "task": "generate_story",
                     *       "chain": [
                     *         {
                     *           "provider": "local",
                     *           "model": "qwen3:4b-instruct"
                     *         }
                     *       ]
                     *     }
                     */
                    "application/json": components["schemas"]["TaskModelsOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description No existe o no pertenece a la persona (mismo mensaje en los dos casos). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "No existe esa conversación o no es tuya."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    usage_today_api_v1_settings_usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "tokens_today": 42000,
                     *       "warning_threshold": 180000,
                     *       "scope": "global"
                     *     }
                     */
                    "application/json": components["schemas"]["UsageTodayOut"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    propose_api_v1_start_propose_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProposeIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "project": "DEMO",
                     *       "project_changed": false,
                     *       "ignored_projects": [],
                     *       "recognized": [],
                     *       "similar": [
                     *         {
                     *           "key": "DEMO-3",
                     *           "summary": "Renovar un préstamo",
                     *           "issue_type": "Story",
                     *           "status": "Abierta"
                     *         }
                     *       ],
                     *       "options": [
                     *         {
                     *           "kind": "evolve",
                     *           "label": "Evolucionar DEMO-3",
                     *           "origin": {
                     *             "kind": "story",
                     *             "key": "DEMO-3",
                     *             "project": "DEMO"
                     *           },
                     *           "issue": {
                     *             "key": "DEMO-3",
                     *             "summary": "Renovar un préstamo",
                     *             "issue_type": "Story",
                     *             "status": "Abierta"
                     *           }
                     *         },
                     *         {
                     *           "kind": "new_need",
                     *           "label": "Crear HU nueva",
                     *           "origin": {
                     *             "kind": "need",
                     *             "text": "Renovar un préstamo desde la app (ficticio).",
                     *             "project": "DEMO"
                     *           }
                     *         }
                     *       ]
                     *     }
                     */
                    "application/json": components["schemas"]["StartProposal"];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    sources_api_v1_start_sources_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SourcesIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example [
                     *       {
                     *         "ref": "DEMO-3",
                     *         "kind": "jira",
                     *         "title": "Renovar un préstamo",
                     *         "category": "Story",
                     *         "required": true
                     *       },
                     *       {
                     *         "ref": "DOC-01",
                     *         "kind": "rag",
                     *         "title": "Reglamento de préstamo",
                     *         "category": "politicas",
                     *         "required": false
                     *       },
                     *       {
                     *         "ref": "memoria-DEMO-2",
                     *         "kind": "memory",
                     *         "title": "Memoria de DEMO-2",
                     *         "category": "memoria",
                     *         "required": false
                     *       }
                     *     ]
                     */
                    "application/json": components["schemas"]["SourcePreview"][];
                };
            };
            /** @description Sin sesión o caducada. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unauthenticated",
                     *         "message": "Inicia sesión para continuar."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "forbidden",
                     *         "message": "No tienes permiso para realizar esta acción."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Incidencia de origen que no existe o no ve la conexión. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "not_found",
                     *         "message": "La incidencia DEMO-999 no existe."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Cuerpo de más de 256 KB. */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "payload_too_large",
                     *         "message": "La petición es demasiado grande."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Petición no válida (sin devolver lo enviado). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "invalid_request",
                     *         "message": "La petición no es válida: revisa password.",
                     *         "retry_after": null
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Límite de un servicio externo (Jira o el LLM). */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "rate_limited",
                     *         "message": "Jira ha alcanzado su límite de peticiones.",
                     *         "retry_after": 30
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Error no previsto (sin detalles internos). */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "unexpected",
                     *         "message": "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Servicio externo caído (Jira, PostgreSQL, Ollama). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "error": {
                     *         "code": "service_unavailable",
                     *         "message": "No se pudo conectar con Jira. Revisa la URL del sitio y la red."
                     *       }
                     *     }
                     */
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
