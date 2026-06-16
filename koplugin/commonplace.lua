-- Commonplace exporter target for KOReader
-- Drops into koreader/plugins/exporter.koplugin/target/commonplace.lua
-- Adds an "Export to Commonplace" option in the exporter menu

local InputDialog = require("ui/widget/inputdialog")
local UIManager = require("ui/uimanager")
local logger = require("logger")
local _ = require("gettext")

local CommonplaceExporter = require("base"):new{
    name = "commonplace",
    is_remote = true,
}

function CommonplaceExporter:isReadyToExport()
    if self.settings.server_url and self.settings.token then
        return true
    end
    return false
end

function CommonplaceExporter:getMenuTable()
    return {
        text = _("Commonplace"),
        checked_func = function() return self:isEnabled() end,
        sub_item_table = {
            {
                text = _("Set server URL"),
                keep_menu_open = true,
                callback = function()
                    local dialog
                    dialog = InputDialog:new{
                        title = _("Commonplace server URL"),
                        input = self.settings.server_url,
                        hint = _("https://example.com:8765"),
                        buttons = {
                            {
                                {
                                    text = _("Cancel"),
                                    callback = function()
                                        UIManager:close(dialog)
                                    end,
                                },
                                {
                                    text = _("Set URL"),
                                    callback = function()
                                        self.settings.server_url = dialog:getInputText()
                                        -- Strip trailing slash
                                        self.settings.server_url = self.settings.server_url:gsub("/+$", "")
                                        self:saveSettings()
                                        UIManager:close(dialog)
                                    end,
                                },
                            },
                        },
                    }
                    UIManager:show(dialog)
                    dialog:onShowKeyboard()
                end,
            },
            {
                text = _("Set API token"),
                keep_menu_open = true,
                callback = function()
                    local dialog
                    dialog = InputDialog:new{
                        title = _("Commonplace API token"),
                        input = self.settings.token,
                        hint = _("Token from the Settings page"),
                        buttons = {
                            {
                                {
                                    text = _("Cancel"),
                                    callback = function()
                                        UIManager:close(dialog)
                                    end,
                                },
                                {
                                    text = _("Set token"),
                                    callback = function()
                                        self.settings.token = dialog:getInputText()
                                        self:saveSettings()
                                        UIManager:close(dialog)
                                    end,
                                },
                            },
                        },
                    }
                    UIManager:show(dialog)
                    dialog:onShowKeyboard()
                end,
            },
            {
                text = _("Export to Commonplace"),
                checked_func = function() return self:isEnabled() end,
                callback = function() self:toggleEnabled() end,
            },
        },
    }
end

function CommonplaceExporter:createHighlights(booknotes)
    local highlights = {}
    local headers = {
        ["Authorization"] = "Token " .. self.settings.token,
    }

    for _, chapter in ipairs(booknotes) do
        for _, clipping in ipairs(chapter) do
            local highlight = {
                text = clipping.text,
                title = booknotes.title,
                author = booknotes.author ~= "" and booknotes.author:gsub("\n", ", ") or nil,
                source_type = "koreader",
                category = "books",
                note = clipping.note,
                location = clipping.page,
                location_type = "order",
                highlighted_at = os.date("!%Y-%m-%dT%TZ", clipping.time),
            }
            table.insert(highlights, highlight)
        end
    end

    local api_url = self.settings.server_url .. "/api/v2/highlights"
    local result, err = self:makeJsonRequest(api_url, "POST",
        { highlights = highlights }, headers)

    if not result then
        logger.warn("error exporting to Commonplace", err)
        return false
    end
    return true
end

function CommonplaceExporter:export(t)
    if not self:isReadyToExport() then
        logger.warn("Commonplace: server_url or token not configured")
        return false
    end
    for _, booknotes in ipairs(t) do
        local ok = self:createHighlights(booknotes)
        if not ok then return false end
    end
    return true
end

return CommonplaceExporter
