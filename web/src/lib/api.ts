/** Named aliases for the generated OpenAPI schema types (regenerate with `npm run gen:api`). */
import type { components } from "@/lib/api-types";

type Schemas = components["schemas"];

export type Me = Schemas["MeResponse"];
export type LoginResponse = Schemas["LoginResponse"];
export type Alias = Schemas["AliasResponse"];
export type AliasPage = Schemas["AliasPage"];
export type AliasCreate = Schemas["AliasCreate"];
export type AliasUpdate = Schemas["AliasUpdate"];
export type AliasState = Schemas["AliasState"];
export type AliasFormat = Schemas["AliasFormat"];
export type BulkAction = Schemas["AliasBulk"]["action"];
export type Contact = Schemas["ContactResponse"];
export type Label = Schemas["LabelResponse"];
export type Recipient = Schemas["RecipientResponse"];
export type BlocklistEntry = Schemas["BlocklistResponse"];
export type QuarantineItem = Schemas["QuarantineResponse"];
export type FailedDelivery = Schemas["FailedDeliveryResponse"];
export type Invite = Schemas["InviteResponse"];
export type SettingsUpdate = Schemas["SettingsUpdate"];
export type BannerPosition = Schemas["BannerPosition"];
export type Activity = Schemas["ActivityResponse"];
export type DailyActivity = Schemas["DailyActivity"];
export type RecentMail = Schemas["RecentMail"];
export type MailOutcome = Schemas["Outcome"];
export type FailureKind = Schemas["FailureKind"];
export type AdminUser = Schemas["AdminUserResponse"];
export type AdminUserUpdate = Schemas["AdminUserUpdate"];
export type Health = Schemas["HealthResponse"];
export type DlqItem = Schemas["DlqItemResponse"];
export type UserRole = Schemas["UserRole"];
export type ApiToken = Schemas["TokenResponse"];
export type ApiTokenCreated = Schemas["TokenCreated"];
export type TokenCreate = Schemas["TokenCreate"];
export type TokenScope = Schemas["TokenCreate"]["scopes"][number];
export type Passkey = Schemas["PasskeyResponse"];
