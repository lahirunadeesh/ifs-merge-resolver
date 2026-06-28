IFS_FILE_TYPES = {
    # Model layer
    ".entity":      "Entity",
    ".projection":  "Projection",
    ".client":      "Client",
    ".fragment":    "Fragment",
    ".enumeration": "Enumeration",

    # Database / DDL layer
    ".ddlsource":   "DDL Source",
    ".cdb":         "CDB",
    ".views":       "Views",
    ".storage":     "Storage",
    ".upg":         "Upgrade",

    # Business logic layer
    ".plsql":       "PL/SQL",
    ".plsvc":       "PL/SVC",
    ".pltst":       "PL/SQL Test",

    # Supporting
    ".utility":     "Utility",
    ".ins":         "Install",
}

# Block identifier rules per file type — used by the merge engine
BLOCK_IDENTIFIERS = {
    ".entity":      "xml_element_name",       # <NAME> inside <ATTRIBUTE> / <ASSOCIATION>
    ".projection":  "dsl_entity_name",        # entity Name { } blocks
    ".client":      "dsl_component_name",     # page/list/group Name { } blocks
    ".fragment":    "dsl_component_name",     # dialog/group/list Name { } blocks
    ".ddlsource":   "code_registration_name", # @CodeRegistration <Name>
    ".cdb":         "code_registration_name", # same pattern as ddlsource
    ".views":       "dsl_view_name",          # view Name { } blocks
    ".plsql":       "line_based",             # line-by-line, no semantic blocks
    ".plsvc":       "line_based",
}
