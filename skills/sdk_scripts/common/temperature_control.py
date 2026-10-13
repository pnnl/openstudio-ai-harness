"""Translated node temperature controls shared by equipment review checks."""


def translated_workspace(model, sdk, label):
    translator = sdk.energyplus.ForwardTranslator()
    workspace = translator.translateModel(model)
    if translator.errors():
        raise ValueError(
            label + ": " + "; ".join(x.logMessage() for x in translator.errors())
        )
    return workspace


def optional_string(obj, index):
    value = obj.getString(index)
    return value.get() if value.is_initialized() else ""


def node_temperature_managers(workspace, sdk, node_name):
    """Match target fields/NodeLists, never an incidental reference-node field."""
    node_lists = {
        x.getString(0).get(): [x.getString(i).get() for i in range(1, x.numFields())]
        for x in workspace.getObjectsByType(sdk.IddObjectType("NodeList"))
    }
    managers = []
    for obj in workspace.objects():
        kind = obj.iddObject().name()
        if not kind.startswith("SetpointManager:"):
            continue
        fields = {
            obj.iddObject().getField(i).get().name(): optional_string(obj, i)
            for i in range(obj.numFields())
        }
        targets = fields.get(
            "Setpoint Node or NodeList Name", fields.get("Setpoint Node Name", "")
        )
        if (
            node_name not in node_lists.get(targets, [targets])
            or fields.get("Control Variable", "Temperature") != "Temperature"
        ):
            continue
        fields.pop("Name", None)
        managers.append(dict(type=kind, fields=fields))
    managers.sort(key=lambda x: (x["type"], str(sorted(x["fields"].items()))))
    return managers
