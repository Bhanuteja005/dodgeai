from dataclasses import dataclass


@dataclass(frozen=True)
class RelationshipRule:
    source_entity: str
    source_field: str
    target_entity: str
    target_field: str
    relationship_label: str


ENTITY_ID_FIELDS: dict[str, tuple[str, ...]] = {
    "sales_order_headers": ("salesOrder",),
    "sales_order_items": ("salesOrder", "salesOrderItem"),
    "sales_order_schedule_lines": ("salesOrder", "salesOrderItem", "scheduleLine"),
    "outbound_delivery_headers": ("deliveryDocument",),
    "outbound_delivery_items": ("deliveryDocument", "deliveryDocumentItem"),
    "billing_document_headers": ("billingDocument",),
    "billing_document_items": ("billingDocument", "billingDocumentItem"),
    "billing_document_cancellations": ("billingDocument", "cancelledBillingDocument"),
    "journal_entry_items_accounts_receivable": ("companyCode", "fiscalYear", "accountingDocument", "accountingDocumentItem"),
    "payments_accounts_receivable": ("companyCode", "fiscalYear", "accountingDocument", "accountingDocumentItem"),
    "business_partners": ("businessPartner",),
    "business_partner_addresses": ("businessPartner", "addressId"),
    "customer_company_assignments": ("customer", "companyCode"),
    "customer_sales_area_assignments": (
        "customer",
        "salesOrganization",
        "distributionChannel",
        "division",
    ),
    "products": ("product",),
    "product_descriptions": ("product", "language"),
    "product_plants": ("product", "plant"),
    "product_storage_locations": ("product", "plant", "storageLocation"),
    "plants": ("plant",),
}


RELATIONSHIP_RULES: tuple[RelationshipRule, ...] = (
    RelationshipRule("sales_order_items", "salesOrder", "sales_order_headers", "salesOrder", "ITEM_OF"),
    RelationshipRule("sales_order_schedule_lines", "salesOrder", "sales_order_headers", "salesOrder", "SCHEDULE_OF_ORDER"),
    RelationshipRule("sales_order_schedule_lines", "salesOrderItem", "sales_order_items", "salesOrderItem", "SCHEDULE_OF_ITEM"),
    RelationshipRule("outbound_delivery_items", "deliveryDocument", "outbound_delivery_headers", "deliveryDocument", "ITEM_OF_DELIVERY"),
    RelationshipRule("outbound_delivery_items", "referenceSdDocument", "sales_order_headers", "salesOrder", "DELIVERY_FOR_ORDER"),
    RelationshipRule("billing_document_items", "billingDocument", "billing_document_headers", "billingDocument", "ITEM_OF_BILLING"),
    RelationshipRule("billing_document_items", "referenceSdDocument", "outbound_delivery_headers", "deliveryDocument", "BILLING_FOR_DELIVERY"),
    RelationshipRule("billing_document_headers", "accountingDocument", "journal_entry_items_accounts_receivable", "accountingDocument", "HAS_JOURNAL_ENTRY"),
    RelationshipRule("journal_entry_items_accounts_receivable", "referenceDocument", "billing_document_headers", "billingDocument", "JOURNAL_FOR_BILLING"),
    RelationshipRule("payments_accounts_receivable", "accountingDocument", "journal_entry_items_accounts_receivable", "accountingDocument", "PAYMENT_FOR_JOURNAL"),
    RelationshipRule("sales_order_headers", "soldToParty", "business_partners", "customer", "ORDERED_BY_CUSTOMER"),
    RelationshipRule("billing_document_headers", "soldToParty", "business_partners", "customer", "BILLED_TO_CUSTOMER"),
    RelationshipRule("business_partner_addresses", "businessPartner", "business_partners", "businessPartner", "ADDRESS_OF"),
    RelationshipRule("sales_order_items", "material", "products", "product", "ORDERED_PRODUCT"),
    RelationshipRule("billing_document_items", "material", "products", "product", "BILLED_PRODUCT"),
    RelationshipRule("product_descriptions", "product", "products", "product", "DESCRIPTION_OF_PRODUCT"),
    RelationshipRule("product_plants", "product", "products", "product", "PRODUCT_IN_PLANT"),
    RelationshipRule("product_plants", "plant", "plants", "plant", "PLANT_FOR_PRODUCT"),
    RelationshipRule("product_storage_locations", "product", "products", "product", "STORED_PRODUCT"),
    RelationshipRule("product_storage_locations", "plant", "plants", "plant", "STORAGE_IN_PLANT"),
    RelationshipRule("outbound_delivery_items", "plant", "plants", "plant", "DELIVERED_FROM_PLANT"),
)
