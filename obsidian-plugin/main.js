"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
const obsidian_1 = require("obsidian");
const DEFAULT_SETTINGS = {
    serverUrl: '',
    apiToken: '',
    outputFolder: 'Commonplace',
    lastSync: '',
    autoSync: true,
    syncInterval: 6,
};
class CommonplacePlugin extends obsidian_1.Plugin {
    constructor() {
        super(...arguments);
        this._intervalHandle = null;
    }
    onload() {
        return __awaiter(this, void 0, void 0, function* () {
            yield this.loadSettings();
            // Register the settings tab
            this.addSettingTab(new CommonplaceSettingTab(this.app, this));
            // Register the sync command
            this.addCommand({
                id: 'sync-from-commonplace',
                name: 'Sync highlights from Commonplace',
                callback: () => this.syncHighlights(),
            });
            // Also add a ribbon icon
            this.addRibbonIcon('download', 'Sync from Commonplace', () => {
                this.syncHighlights();
            });
            // Auto-sync on startup if configured
            if (this.settings.autoSync) {
                this.syncHighlights();
            }
            // Periodic sync while open
            this.setupInterval();
        });
    }
    setupInterval() {
        if (this._intervalHandle) {
            clearInterval(this._intervalHandle);
        }
        const hours = this.settings.syncInterval;
        if (hours > 0 && this.settings.serverUrl && this.settings.apiToken) {
            this._intervalHandle = window.setInterval(() => {
                this.syncHighlights();
            }, hours * 3600000);
        }
    }
    loadSettings() {
        return __awaiter(this, void 0, void 0, function* () {
            this.settings = Object.assign({}, DEFAULT_SETTINGS, yield this.loadData());
        });
    }
    saveSettings() {
        return __awaiter(this, void 0, void 0, function* () {
            yield this.saveData(this.settings);
        });
    }
    syncHighlights() {
        return __awaiter(this, void 0, void 0, function* () {
            // Validate settings
            if (!this.settings.serverUrl || !this.settings.apiToken) {
                new obsidian_1.Notice('⚠️ Commonplace: Configure server URL and API token in Settings first');
                return;
            }
            new obsidian_1.Notice('🔄 Syncing from Commonplace...');
            const serverUrl = this.settings.serverUrl.replace(/\/+$/, '');
            const since = this.settings.lastSync || '';
            try {
                const url = `${serverUrl}/api/export${since ? '?since=' + encodeURIComponent(since) : ''}`;
                const response = yield (0, obsidian_1.requestUrl)({
                    url: url,
                    method: 'GET',
                    headers: {
                        'Authorization': `Token ${this.settings.apiToken}`,
                    },
                });
                if (response.status !== 200) {
                    new obsidian_1.Notice(`⚠️ Commonplace sync failed: HTTP ${response.status}`);
                    return;
                }
                const data = response.json;
                yield this.writeHighlights(data);
                // Update last sync timestamp
                this.settings.lastSync = new Date().toISOString();
                yield this.saveSettings();
                new obsidian_1.Notice(`✅ Commonplace: Synced ${data.total} highlights from ${data.total_books} books`);
            }
            catch (e) {
                new obsidian_1.Notice(`⚠️ Commonplace sync error: ${e.message || e}`);
            }
        });
    }
    writeHighlights(data) {
        return __awaiter(this, void 0, void 0, function* () {
            // Ensure the output folder exists
            const folderPath = this.settings.outputFolder || 'Commonplace';
            const folder = this.app.vault.getAbstractFileByPath(folderPath);
            if (!folder) {
                yield this.app.vault.createFolder(folderPath);
            }
            for (const book of data.books) {
                const safeFileName = this.sanitizeFileName(`${book.title}.md`);
                const filePath = `${folderPath}/${safeFileName}`;
                // Build markdown content matching Readwise format
                const content = this.buildMarkdown(book);
                // Write or update the file
                const existing = this.app.vault.getAbstractFileByPath(filePath);
                if (existing) {
                    yield this.app.vault.modify(existing, content);
                }
                else {
                    yield this.app.vault.create(filePath, content);
                }
            }
        });
    }
    buildMarkdown(book) {
        const lines = [];
        lines.push(`# ${book.title}`);
        lines.push('');
        lines.push('## Metadata');
        if (book.author) {
            lines.push(`- Author: [[${book.author}]]`);
        }
        lines.push(`- Full Title: ${book.title}`);
        lines.push('- Category: #books');
        lines.push('');
        lines.push('## Highlights');
        lines.push('');
        for (const h of book.highlights) {
            const pageStr = h.page ? ` (p. ${h.page})` : '';
            lines.push(`- ${h.text}${pageStr}`);
            if (h.tags && h.tags.length > 0) {
                const tagStr = h.tags.map(t => `[[${t}]]`).join(' ');
                lines.push(`    - Tags: ${tagStr}`);
            }
            if (h.note) {
                lines.push(`    - **Note:** ${h.note}`);
            }
            lines.push('');
        }
        return lines.join('\n');
    }
    sanitizeFileName(name) {
        return name.replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, ' ');
    }
}
exports.default = CommonplacePlugin;
class CommonplaceSettingTab extends obsidian_1.PluginSettingTab {
    constructor(app, plugin) {
        super(app, plugin);
        this.plugin = plugin;
    }
    display() {
        const { containerEl } = this;
        containerEl.empty();
        containerEl.createEl('h2', { text: 'Commonplace Sync Settings' });
        new obsidian_1.Setting(containerEl)
            .setName('Server URL')
            .setDesc('Your Commonplace server URL (e.g. https://commonplace.yourdomain.com)')
            .addText(text => text
            .setPlaceholder('https://...')
            .setValue(this.plugin.settings.serverUrl)
            .onChange((value) => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.serverUrl = value;
            yield this.plugin.saveSettings();
            this.plugin.setupInterval();
        })));
        new obsidian_1.Setting(containerEl)
            .setName('API Token')
            .setDesc('API token from Commonplace Settings page')
            .addText(text => text
            .setPlaceholder('your-token')
            .setValue(this.plugin.settings.apiToken)
            .onChange((value) => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.apiToken = value;
            yield this.plugin.saveSettings();
            this.plugin.setupInterval();
        })));
        new obsidian_1.Setting(containerEl)
            .setName('Output Folder')
            .setDesc('Folder in your vault where highlight notes will be saved')
            .addText(text => text
            .setPlaceholder('Commonplace')
            .setValue(this.plugin.settings.outputFolder)
            .onChange((value) => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.outputFolder = value;
            yield this.plugin.saveSettings();
        })));
        new obsidian_1.Setting(containerEl)
            .setName('Auto-sync on startup')
            .setDesc('Automatically sync highlights when Obsidian opens')
            .addToggle(toggle => toggle
            .setValue(this.plugin.settings.autoSync)
            .onChange((value) => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.autoSync = value;
            yield this.plugin.saveSettings();
        })));
        new obsidian_1.Setting(containerEl)
            .setName('Sync interval')
            .setDesc('How often to auto-sync while Obsidian is open (hours, 0 = off)')
            .addSlider(slider => slider
            .setLimits(0, 24, 1)
            .setValue(this.plugin.settings.syncInterval)
            .setDynamicTooltip()
            .onChange((value) => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.syncInterval = value;
            yield this.plugin.saveSettings();
            this.plugin.setupInterval();
        })));
        new obsidian_1.Setting(containerEl)
            .setName('Last Sync')
            .setDesc(this.plugin.settings.lastSync
            ? `Last synced: ${this.plugin.settings.lastSync}`
            : 'No sync yet')
            .addButton(btn => btn
            .setButtonText('Sync Now')
            .onClick(() => {
            this.plugin.syncHighlights();
        }));
        containerEl.createEl('hr');
        new obsidian_1.Setting(containerEl)
            .setName('Sync All')
            .setDesc('Clear the last sync timestamp and pull everything again')
            .addButton(btn => btn
            .setButtonText('Reset and Sync All')
            .setWarning()
            .onClick(() => __awaiter(this, void 0, void 0, function* () {
            this.plugin.settings.lastSync = '';
            yield this.plugin.saveSettings();
            this.display();
            this.plugin.syncHighlights();
        })));
    }
}
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoibWFpbi5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbIm1haW4udHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7QUFBQSx1Q0FBc0Y7QUFXdEYsTUFBTSxnQkFBZ0IsR0FBd0I7SUFDMUMsU0FBUyxFQUFFLEVBQUU7SUFDYixRQUFRLEVBQUUsRUFBRTtJQUNaLFlBQVksRUFBRSxhQUFhO0lBQzNCLFFBQVEsRUFBRSxFQUFFO0lBQ1osUUFBUSxFQUFFLElBQUk7SUFDZCxZQUFZLEVBQUUsQ0FBQztDQUNsQixDQUFDO0FBMkJGLE1BQXFCLGlCQUFrQixTQUFRLGlCQUFNO0lBQXJEOztRQUVJLG9CQUFlLEdBQWtCLElBQUksQ0FBQztJQWtKMUMsQ0FBQztJQWhKUyxNQUFNOztZQUNSLE1BQU0sSUFBSSxDQUFDLFlBQVksRUFBRSxDQUFDO1lBRTFCLDRCQUE0QjtZQUM1QixJQUFJLENBQUMsYUFBYSxDQUFDLElBQUkscUJBQXFCLENBQUMsSUFBSSxDQUFDLEdBQUcsRUFBRSxJQUFJLENBQUMsQ0FBQyxDQUFDO1lBRTlELDRCQUE0QjtZQUM1QixJQUFJLENBQUMsVUFBVSxDQUFDO2dCQUNaLEVBQUUsRUFBRSx1QkFBdUI7Z0JBQzNCLElBQUksRUFBRSxrQ0FBa0M7Z0JBQ3hDLFFBQVEsRUFBRSxHQUFHLEVBQUUsQ0FBQyxJQUFJLENBQUMsY0FBYyxFQUFFO2FBQ3hDLENBQUMsQ0FBQztZQUVILHlCQUF5QjtZQUN6QixJQUFJLENBQUMsYUFBYSxDQUFDLFVBQVUsRUFBRSx1QkFBdUIsRUFBRSxHQUFHLEVBQUU7Z0JBQ3pELElBQUksQ0FBQyxjQUFjLEVBQUUsQ0FBQztZQUMxQixDQUFDLENBQUMsQ0FBQztZQUVILHFDQUFxQztZQUNyQyxJQUFJLElBQUksQ0FBQyxRQUFRLENBQUMsUUFBUSxFQUFFLENBQUM7Z0JBQ3pCLElBQUksQ0FBQyxjQUFjLEVBQUUsQ0FBQztZQUMxQixDQUFDO1lBRUQsMkJBQTJCO1lBQzNCLElBQUksQ0FBQyxhQUFhLEVBQUUsQ0FBQztRQUN6QixDQUFDO0tBQUE7SUFFRCxhQUFhO1FBQ1QsSUFBSSxJQUFJLENBQUMsZUFBZSxFQUFFLENBQUM7WUFDdkIsYUFBYSxDQUFDLElBQUksQ0FBQyxlQUFlLENBQUMsQ0FBQztRQUN4QyxDQUFDO1FBQ0QsTUFBTSxLQUFLLEdBQUcsSUFBSSxDQUFDLFFBQVEsQ0FBQyxZQUFZLENBQUM7UUFDekMsSUFBSSxLQUFLLEdBQUcsQ0FBQyxJQUFJLElBQUksQ0FBQyxRQUFRLENBQUMsU0FBUyxJQUFJLElBQUksQ0FBQyxRQUFRLENBQUMsUUFBUSxFQUFFLENBQUM7WUFDakUsSUFBSSxDQUFDLGVBQWUsR0FBRyxNQUFNLENBQUMsV0FBVyxDQUFDLEdBQUcsRUFBRTtnQkFDM0MsSUFBSSxDQUFDLGNBQWMsRUFBRSxDQUFDO1lBQzFCLENBQUMsRUFBRSxLQUFLLEdBQUcsT0FBTyxDQUFDLENBQUM7UUFDeEIsQ0FBQztJQUNMLENBQUM7SUFFSyxZQUFZOztZQUNkLElBQUksQ0FBQyxRQUFRLEdBQUcsTUFBTSxDQUFDLE1BQU0sQ0FBQyxFQUFFLEVBQUUsZ0JBQWdCLEVBQUUsTUFBTSxJQUFJLENBQUMsUUFBUSxFQUFFLENBQUMsQ0FBQztRQUMvRSxDQUFDO0tBQUE7SUFFSyxZQUFZOztZQUNkLE1BQU0sSUFBSSxDQUFDLFFBQVEsQ0FBQyxJQUFJLENBQUMsUUFBUSxDQUFDLENBQUM7UUFDdkMsQ0FBQztLQUFBO0lBRUssY0FBYzs7WUFDaEIsb0JBQW9CO1lBQ3BCLElBQUksQ0FBQyxJQUFJLENBQUMsUUFBUSxDQUFDLFNBQVMsSUFBSSxDQUFDLElBQUksQ0FBQyxRQUFRLENBQUMsUUFBUSxFQUFFLENBQUM7Z0JBQ3RELElBQUksaUJBQU0sQ0FBQyxzRUFBc0UsQ0FBQyxDQUFDO2dCQUNuRixPQUFPO1lBQ1gsQ0FBQztZQUVELElBQUksaUJBQU0sQ0FBQyxnQ0FBZ0MsQ0FBQyxDQUFDO1lBQzdDLE1BQU0sU0FBUyxHQUFHLElBQUksQ0FBQyxRQUFRLENBQUMsU0FBUyxDQUFDLE9BQU8sQ0FBQyxNQUFNLEVBQUUsRUFBRSxDQUFDLENBQUM7WUFDOUQsTUFBTSxLQUFLLEdBQUcsSUFBSSxDQUFDLFFBQVEsQ0FBQyxRQUFRLElBQUksRUFBRSxDQUFDO1lBRTNDLElBQUksQ0FBQztnQkFDRCxNQUFNLEdBQUcsR0FBRyxHQUFHLFNBQVMsY0FBYyxLQUFLLENBQUMsQ0FBQyxDQUFDLFNBQVMsR0FBRyxrQkFBa0IsQ0FBQyxLQUFLLENBQUMsQ0FBQyxDQUFDLENBQUMsRUFBRSxFQUFFLENBQUM7Z0JBQzNGLE1BQU0sUUFBUSxHQUFHLE1BQU0sSUFBQSxxQkFBVSxFQUFDO29CQUM5QixHQUFHLEVBQUUsR0FBRztvQkFDUixNQUFNLEVBQUUsS0FBSztvQkFDYixPQUFPLEVBQUU7d0JBQ0wsZUFBZSxFQUFFLFNBQVMsSUFBSSxDQUFDLFFBQVEsQ0FBQyxRQUFRLEVBQUU7cUJBQ3JEO2lCQUNKLENBQUMsQ0FBQztnQkFFSCxJQUFJLFFBQVEsQ0FBQyxNQUFNLEtBQUssR0FBRyxFQUFFLENBQUM7b0JBQzFCLElBQUksaUJBQU0sQ0FBQyxvQ0FBb0MsUUFBUSxDQUFDLE1BQU0sRUFBRSxDQUFDLENBQUM7b0JBQ2xFLE9BQU87Z0JBQ1gsQ0FBQztnQkFFRCxNQUFNLElBQUksR0FBbUIsUUFBUSxDQUFDLElBQUksQ0FBQztnQkFDM0MsTUFBTSxJQUFJLENBQUMsZUFBZSxDQUFDLElBQUksQ0FBQyxDQUFDO2dCQUVqQyw2QkFBNkI7Z0JBQzdCLElBQUksQ0FBQyxRQUFRLENBQUMsUUFBUSxHQUFHLElBQUksSUFBSSxFQUFFLENBQUMsV0FBVyxFQUFFLENBQUM7Z0JBQ2xELE1BQU0sSUFBSSxDQUFDLFlBQVksRUFBRSxDQUFDO2dCQUUxQixJQUFJLGlCQUFNLENBQUMseUJBQXlCLElBQUksQ0FBQyxLQUFLLG9CQUFvQixJQUFJLENBQUMsV0FBVyxRQUFRLENBQUMsQ0FBQztZQUNoRyxDQUFDO1lBQUMsT0FBTyxDQUFDLEVBQUUsQ0FBQztnQkFDVCxJQUFJLGlCQUFNLENBQUMsOEJBQThCLENBQUMsQ0FBQyxPQUFPLElBQUksQ0FBQyxFQUFFLENBQUMsQ0FBQztZQUMvRCxDQUFDO1FBQ0wsQ0FBQztLQUFBO0lBRUssZUFBZSxDQUFDLElBQW9COztZQUN0QyxrQ0FBa0M7WUFDbEMsTUFBTSxVQUFVLEdBQUcsSUFBSSxDQUFDLFFBQVEsQ0FBQyxZQUFZLElBQUksYUFBYSxDQUFDO1lBQy9ELE1BQU0sTUFBTSxHQUFHLElBQUksQ0FBQyxHQUFHLENBQUMsS0FBSyxDQUFDLHFCQUFxQixDQUFDLFVBQVUsQ0FBQyxDQUFDO1lBQ2hFLElBQUksQ0FBQyxNQUFNLEVBQUUsQ0FBQztnQkFDVixNQUFNLElBQUksQ0FBQyxHQUFHLENBQUMsS0FBSyxDQUFDLFlBQVksQ0FBQyxVQUFVLENBQUMsQ0FBQztZQUNsRCxDQUFDO1lBRUQsS0FBSyxNQUFNLElBQUksSUFBSSxJQUFJLENBQUMsS0FBSyxFQUFFLENBQUM7Z0JBQzVCLE1BQU0sWUFBWSxHQUFHLElBQUksQ0FBQyxnQkFBZ0IsQ0FBQyxHQUFHLElBQUksQ0FBQyxLQUFLLEtBQUssQ0FBQyxDQUFDO2dCQUMvRCxNQUFNLFFBQVEsR0FBRyxHQUFHLFVBQVUsSUFBSSxZQUFZLEVBQUUsQ0FBQztnQkFFakQsa0RBQWtEO2dCQUNsRCxNQUFNLE9BQU8sR0FBRyxJQUFJLENBQUMsYUFBYSxDQUFDLElBQUksQ0FBQyxDQUFDO2dCQUV6QywyQkFBMkI7Z0JBQzNCLE1BQU0sUUFBUSxHQUFHLElBQUksQ0FBQyxHQUFHLENBQUMsS0FBSyxDQUFDLHFCQUFxQixDQUFDLFFBQVEsQ0FBQyxDQUFDO2dCQUNoRSxJQUFJLFFBQVEsRUFBRSxDQUFDO29CQUNYLE1BQU0sSUFBSSxDQUFDLEdBQUcsQ0FBQyxLQUFLLENBQUMsTUFBTSxDQUFDLFFBQWUsRUFBRSxPQUFPLENBQUMsQ0FBQztnQkFDMUQsQ0FBQztxQkFBTSxDQUFDO29CQUNKLE1BQU0sSUFBSSxDQUFDLEdBQUcsQ0FBQyxLQUFLLENBQUMsTUFBTSxDQUFDLFFBQVEsRUFBRSxPQUFPLENBQUMsQ0FBQztnQkFDbkQsQ0FBQztZQUNMLENBQUM7UUFDTCxDQUFDO0tBQUE7SUFFRCxhQUFhLENBQUMsSUFBYztRQUN4QixNQUFNLEtBQUssR0FBYSxFQUFFLENBQUM7UUFDM0IsS0FBSyxDQUFDLElBQUksQ0FBQyxLQUFLLElBQUksQ0FBQyxLQUFLLEVBQUUsQ0FBQyxDQUFDO1FBQzlCLEtBQUssQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLENBQUM7UUFDZixLQUFLLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxDQUFDO1FBQzFCLElBQUksSUFBSSxDQUFDLE1BQU0sRUFBRSxDQUFDO1lBQ2QsS0FBSyxDQUFDLElBQUksQ0FBQyxlQUFlLElBQUksQ0FBQyxNQUFNLElBQUksQ0FBQyxDQUFDO1FBQy9DLENBQUM7UUFDRCxLQUFLLENBQUMsSUFBSSxDQUFDLGlCQUFpQixJQUFJLENBQUMsS0FBSyxFQUFFLENBQUMsQ0FBQztRQUMxQyxLQUFLLENBQUMsSUFBSSxDQUFDLG9CQUFvQixDQUFDLENBQUM7UUFDakMsS0FBSyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsQ0FBQztRQUNmLEtBQUssQ0FBQyxJQUFJLENBQUMsZUFBZSxDQUFDLENBQUM7UUFDNUIsS0FBSyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsQ0FBQztRQUVmLEtBQUssTUFBTSxDQUFDLElBQUksSUFBSSxDQUFDLFVBQVUsRUFBRSxDQUFDO1lBQzlCLE1BQU0sT0FBTyxHQUFHLENBQUMsQ0FBQyxJQUFJLENBQUMsQ0FBQyxDQUFDLFFBQVEsQ0FBQyxDQUFDLElBQUksR0FBRyxDQUFDLENBQUMsQ0FBQyxFQUFFLENBQUM7WUFDaEQsS0FBSyxDQUFDLElBQUksQ0FBQyxLQUFLLENBQUMsQ0FBQyxJQUFJLEdBQUcsT0FBTyxFQUFFLENBQUMsQ0FBQztZQUNwQyxJQUFJLENBQUMsQ0FBQyxJQUFJLElBQUksQ0FBQyxDQUFDLElBQUksQ0FBQyxNQUFNLEdBQUcsQ0FBQyxFQUFFLENBQUM7Z0JBQzlCLE1BQU0sTUFBTSxHQUFHLENBQUMsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLENBQUMsQ0FBQyxFQUFFLENBQUMsS0FBSyxDQUFDLElBQUksQ0FBQyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsQ0FBQztnQkFDckQsS0FBSyxDQUFDLElBQUksQ0FBQyxlQUFlLE1BQU0sRUFBRSxDQUFDLENBQUM7WUFDeEMsQ0FBQztZQUNELElBQUksQ0FBQyxDQUFDLElBQUksRUFBRSxDQUFDO2dCQUNULEtBQUssQ0FBQyxJQUFJLENBQUMsbUJBQW1CLENBQUMsQ0FBQyxJQUFJLEVBQUUsQ0FBQyxDQUFDO1lBQzVDLENBQUM7WUFDRCxLQUFLLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxDQUFDO1FBQ25CLENBQUM7UUFFRCxPQUFPLEtBQUssQ0FBQyxJQUFJLENBQUMsSUFBSSxDQUFDLENBQUM7SUFDNUIsQ0FBQztJQUVELGdCQUFnQixDQUFDLElBQVk7UUFDekIsT0FBTyxJQUFJLENBQUMsT0FBTyxDQUFDLGVBQWUsRUFBRSxHQUFHLENBQUMsQ0FBQyxPQUFPLENBQUMsTUFBTSxFQUFFLEdBQUcsQ0FBQyxDQUFDO0lBQ25FLENBQUM7Q0FDSjtBQXBKRCxvQ0FvSkM7QUFFRCxNQUFNLHFCQUFzQixTQUFRLDJCQUFnQjtJQUdoRCxZQUFZLEdBQVEsRUFBRSxNQUF5QjtRQUMzQyxLQUFLLENBQUMsR0FBRyxFQUFFLE1BQU0sQ0FBQyxDQUFDO1FBQ25CLElBQUksQ0FBQyxNQUFNLEdBQUcsTUFBTSxDQUFDO0lBQ3pCLENBQUM7SUFFRCxPQUFPO1FBQ0gsTUFBTSxFQUFFLFdBQVcsRUFBRSxHQUFHLElBQUksQ0FBQztRQUM3QixXQUFXLENBQUMsS0FBSyxFQUFFLENBQUM7UUFFcEIsV0FBVyxDQUFDLFFBQVEsQ0FBQyxJQUFJLEVBQUUsRUFBRSxJQUFJLEVBQUUsMkJBQTJCLEVBQUUsQ0FBQyxDQUFDO1FBRWxFLElBQUksa0JBQU8sQ0FBQyxXQUFXLENBQUM7YUFDbkIsT0FBTyxDQUFDLFlBQVksQ0FBQzthQUNyQixPQUFPLENBQUMsdUVBQXVFLENBQUM7YUFDaEYsT0FBTyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsSUFBSTthQUNoQixjQUFjLENBQUMsYUFBYSxDQUFDO2FBQzdCLFFBQVEsQ0FBQyxJQUFJLENBQUMsTUFBTSxDQUFDLFFBQVEsQ0FBQyxTQUFTLENBQUM7YUFDeEMsUUFBUSxDQUFDLENBQU8sS0FBSyxFQUFFLEVBQUU7WUFDdEIsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsU0FBUyxHQUFHLEtBQUssQ0FBQztZQUN2QyxNQUFNLElBQUksQ0FBQyxNQUFNLENBQUMsWUFBWSxFQUFFLENBQUM7WUFDakMsSUFBSSxDQUFDLE1BQU0sQ0FBQyxhQUFhLEVBQUUsQ0FBQztRQUNoQyxDQUFDLENBQUEsQ0FBQyxDQUFDLENBQUM7UUFFWixJQUFJLGtCQUFPLENBQUMsV0FBVyxDQUFDO2FBQ25CLE9BQU8sQ0FBQyxXQUFXLENBQUM7YUFDcEIsT0FBTyxDQUFDLDBDQUEwQyxDQUFDO2FBQ25ELE9BQU8sQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLElBQUk7YUFDaEIsY0FBYyxDQUFDLFlBQVksQ0FBQzthQUM1QixRQUFRLENBQUMsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUSxDQUFDO2FBQ3ZDLFFBQVEsQ0FBQyxDQUFPLEtBQUssRUFBRSxFQUFFO1lBQ3RCLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFFBQVEsR0FBRyxLQUFLLENBQUM7WUFDdEMsTUFBTSxJQUFJLENBQUMsTUFBTSxDQUFDLFlBQVksRUFBRSxDQUFDO1lBQ2pDLElBQUksQ0FBQyxNQUFNLENBQUMsYUFBYSxFQUFFLENBQUM7UUFDaEMsQ0FBQyxDQUFBLENBQUMsQ0FBQyxDQUFDO1FBRVosSUFBSSxrQkFBTyxDQUFDLFdBQVcsQ0FBQzthQUNuQixPQUFPLENBQUMsZUFBZSxDQUFDO2FBQ3hCLE9BQU8sQ0FBQywwREFBMEQsQ0FBQzthQUNuRSxPQUFPLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxJQUFJO2FBQ2hCLGNBQWMsQ0FBQyxhQUFhLENBQUM7YUFDN0IsUUFBUSxDQUFDLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFlBQVksQ0FBQzthQUMzQyxRQUFRLENBQUMsQ0FBTyxLQUFLLEVBQUUsRUFBRTtZQUN0QixJQUFJLENBQUMsTUFBTSxDQUFDLFFBQVEsQ0FBQyxZQUFZLEdBQUcsS0FBSyxDQUFDO1lBQzFDLE1BQU0sSUFBSSxDQUFDLE1BQU0sQ0FBQyxZQUFZLEVBQUUsQ0FBQztRQUNyQyxDQUFDLENBQUEsQ0FBQyxDQUFDLENBQUM7UUFFWixJQUFJLGtCQUFPLENBQUMsV0FBVyxDQUFDO2FBQ25CLE9BQU8sQ0FBQyxzQkFBc0IsQ0FBQzthQUMvQixPQUFPLENBQUMsbURBQW1ELENBQUM7YUFDNUQsU0FBUyxDQUFDLE1BQU0sQ0FBQyxFQUFFLENBQUMsTUFBTTthQUN0QixRQUFRLENBQUMsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUSxDQUFDO2FBQ3ZDLFFBQVEsQ0FBQyxDQUFPLEtBQUssRUFBRSxFQUFFO1lBQ3RCLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFFBQVEsR0FBRyxLQUFLLENBQUM7WUFDdEMsTUFBTSxJQUFJLENBQUMsTUFBTSxDQUFDLFlBQVksRUFBRSxDQUFDO1FBQ3JDLENBQUMsQ0FBQSxDQUFDLENBQUMsQ0FBQztRQUVaLElBQUksa0JBQU8sQ0FBQyxXQUFXLENBQUM7YUFDbkIsT0FBTyxDQUFDLGVBQWUsQ0FBQzthQUN4QixPQUFPLENBQUMsZ0VBQWdFLENBQUM7YUFDekUsU0FBUyxDQUFDLE1BQU0sQ0FBQyxFQUFFLENBQUMsTUFBTTthQUN0QixTQUFTLENBQUMsQ0FBQyxFQUFFLEVBQUUsRUFBRSxDQUFDLENBQUM7YUFDbkIsUUFBUSxDQUFDLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFlBQVksQ0FBQzthQUMzQyxpQkFBaUIsRUFBRTthQUNuQixRQUFRLENBQUMsQ0FBTyxLQUFLLEVBQUUsRUFBRTtZQUN0QixJQUFJLENBQUMsTUFBTSxDQUFDLFFBQVEsQ0FBQyxZQUFZLEdBQUcsS0FBSyxDQUFDO1lBQzFDLE1BQU0sSUFBSSxDQUFDLE1BQU0sQ0FBQyxZQUFZLEVBQUUsQ0FBQztZQUNqQyxJQUFJLENBQUMsTUFBTSxDQUFDLGFBQWEsRUFBRSxDQUFDO1FBQ2hDLENBQUMsQ0FBQSxDQUFDLENBQUMsQ0FBQztRQUVaLElBQUksa0JBQU8sQ0FBQyxXQUFXLENBQUM7YUFDbkIsT0FBTyxDQUFDLFdBQVcsQ0FBQzthQUNwQixPQUFPLENBQUMsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUTtZQUNsQyxDQUFDLENBQUMsZ0JBQWdCLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFFBQVEsRUFBRTtZQUNqRCxDQUFDLENBQUMsYUFBYSxDQUFDO2FBQ25CLFNBQVMsQ0FBQyxHQUFHLENBQUMsRUFBRSxDQUFDLEdBQUc7YUFDaEIsYUFBYSxDQUFDLFVBQVUsQ0FBQzthQUN6QixPQUFPLENBQUMsR0FBRyxFQUFFO1lBQ1YsSUFBSSxDQUFDLE1BQU0sQ0FBQyxjQUFjLEVBQUUsQ0FBQztRQUNqQyxDQUFDLENBQUMsQ0FBQyxDQUFDO1FBRVosV0FBVyxDQUFDLFFBQVEsQ0FBQyxJQUFJLENBQUMsQ0FBQztRQUUzQixJQUFJLGtCQUFPLENBQUMsV0FBVyxDQUFDO2FBQ25CLE9BQU8sQ0FBQyxVQUFVLENBQUM7YUFDbkIsT0FBTyxDQUFDLHlEQUF5RCxDQUFDO2FBQ2xFLFNBQVMsQ0FBQyxHQUFHLENBQUMsRUFBRSxDQUFDLEdBQUc7YUFDaEIsYUFBYSxDQUFDLG9CQUFvQixDQUFDO2FBQ25DLFVBQVUsRUFBRTthQUNaLE9BQU8sQ0FBQyxHQUFTLEVBQUU7WUFDaEIsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUSxHQUFHLEVBQUUsQ0FBQztZQUNuQyxNQUFNLElBQUksQ0FBQyxNQUFNLENBQUMsWUFBWSxFQUFFLENBQUM7WUFDakMsSUFBSSxDQUFDLE9BQU8sRUFBRSxDQUFDO1lBQ2YsSUFBSSxDQUFDLE1BQU0sQ0FBQyxjQUFjLEVBQUUsQ0FBQztRQUNqQyxDQUFDLENBQUEsQ0FBQyxDQUFDLENBQUM7SUFDaEIsQ0FBQztDQUNKIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0IHsgQXBwLCBQbHVnaW4sIFBsdWdpblNldHRpbmdUYWIsIFNldHRpbmcsIE5vdGljZSwgcmVxdWVzdFVybCB9IGZyb20gJ29ic2lkaWFuJztcblxuaW50ZXJmYWNlIENvbW1vbnBsYWNlU2V0dGluZ3Mge1xuICAgIHNlcnZlclVybDogc3RyaW5nO1xuICAgIGFwaVRva2VuOiBzdHJpbmc7XG4gICAgb3V0cHV0Rm9sZGVyOiBzdHJpbmc7XG4gICAgbGFzdFN5bmM6IHN0cmluZztcbiAgICBhdXRvU3luYzogYm9vbGVhbjtcbiAgICBzeW5jSW50ZXJ2YWw6IG51bWJlcjtcbn1cblxuY29uc3QgREVGQVVMVF9TRVRUSU5HUzogQ29tbW9ucGxhY2VTZXR0aW5ncyA9IHtcbiAgICBzZXJ2ZXJVcmw6ICcnLFxuICAgIGFwaVRva2VuOiAnJyxcbiAgICBvdXRwdXRGb2xkZXI6ICdDb21tb25wbGFjZScsXG4gICAgbGFzdFN5bmM6ICcnLFxuICAgIGF1dG9TeW5jOiB0cnVlLFxuICAgIHN5bmNJbnRlcnZhbDogNixcbn07XG5cbmludGVyZmFjZSBIaWdobGlnaHREYXRhIHtcbiAgICBpZDogbnVtYmVyO1xuICAgIHRleHQ6IHN0cmluZztcbiAgICBub3RlOiBzdHJpbmcgfCBudWxsO1xuICAgIHBhZ2U6IG51bWJlciB8IG51bGw7XG4gICAgY2hhcHRlcjogc3RyaW5nIHwgbnVsbDtcbiAgICBjb2xvcjogc3RyaW5nIHwgbnVsbDtcbiAgICBmYXZvcml0ZTogYm9vbGVhbjtcbiAgICBoaWdobGlnaHRlZF9hdDogc3RyaW5nIHwgbnVsbDtcbiAgICBjcmVhdGVkX2F0OiBzdHJpbmcgfCBudWxsO1xuICAgIHRhZ3M6IHN0cmluZ1tdO1xufVxuXG5pbnRlcmZhY2UgQm9va0RhdGEge1xuICAgIHRpdGxlOiBzdHJpbmc7XG4gICAgYXV0aG9yOiBzdHJpbmc7XG4gICAgaGlnaGxpZ2h0czogSGlnaGxpZ2h0RGF0YVtdO1xufVxuXG5pbnRlcmZhY2UgRXhwb3J0UmVzcG9uc2Uge1xuICAgIGJvb2tzOiBCb29rRGF0YVtdO1xuICAgIHRvdGFsOiBudW1iZXI7XG4gICAgdG90YWxfYm9va3M6IG51bWJlcjtcbn1cblxuZXhwb3J0IGRlZmF1bHQgY2xhc3MgQ29tbW9ucGxhY2VQbHVnaW4gZXh0ZW5kcyBQbHVnaW4ge1xuICAgIHNldHRpbmdzOiBDb21tb25wbGFjZVNldHRpbmdzO1xuICAgIF9pbnRlcnZhbEhhbmRsZTogbnVtYmVyIHwgbnVsbCA9IG51bGw7XG5cbiAgICBhc3luYyBvbmxvYWQoKSB7XG4gICAgICAgIGF3YWl0IHRoaXMubG9hZFNldHRpbmdzKCk7XG5cbiAgICAgICAgLy8gUmVnaXN0ZXIgdGhlIHNldHRpbmdzIHRhYlxuICAgICAgICB0aGlzLmFkZFNldHRpbmdUYWIobmV3IENvbW1vbnBsYWNlU2V0dGluZ1RhYih0aGlzLmFwcCwgdGhpcykpO1xuXG4gICAgICAgIC8vIFJlZ2lzdGVyIHRoZSBzeW5jIGNvbW1hbmRcbiAgICAgICAgdGhpcy5hZGRDb21tYW5kKHtcbiAgICAgICAgICAgIGlkOiAnc3luYy1mcm9tLWNvbW1vbnBsYWNlJyxcbiAgICAgICAgICAgIG5hbWU6ICdTeW5jIGhpZ2hsaWdodHMgZnJvbSBDb21tb25wbGFjZScsXG4gICAgICAgICAgICBjYWxsYmFjazogKCkgPT4gdGhpcy5zeW5jSGlnaGxpZ2h0cygpLFxuICAgICAgICB9KTtcblxuICAgICAgICAvLyBBbHNvIGFkZCBhIHJpYmJvbiBpY29uXG4gICAgICAgIHRoaXMuYWRkUmliYm9uSWNvbignZG93bmxvYWQnLCAnU3luYyBmcm9tIENvbW1vbnBsYWNlJywgKCkgPT4ge1xuICAgICAgICAgICAgdGhpcy5zeW5jSGlnaGxpZ2h0cygpO1xuICAgICAgICB9KTtcblxuICAgICAgICAvLyBBdXRvLXN5bmMgb24gc3RhcnR1cCBpZiBjb25maWd1cmVkXG4gICAgICAgIGlmICh0aGlzLnNldHRpbmdzLmF1dG9TeW5jKSB7XG4gICAgICAgICAgICB0aGlzLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgIH1cblxuICAgICAgICAvLyBQZXJpb2RpYyBzeW5jIHdoaWxlIG9wZW5cbiAgICAgICAgdGhpcy5zZXR1cEludGVydmFsKCk7XG4gICAgfVxuXG4gICAgc2V0dXBJbnRlcnZhbCgpIHtcbiAgICAgICAgaWYgKHRoaXMuX2ludGVydmFsSGFuZGxlKSB7XG4gICAgICAgICAgICBjbGVhckludGVydmFsKHRoaXMuX2ludGVydmFsSGFuZGxlKTtcbiAgICAgICAgfVxuICAgICAgICBjb25zdCBob3VycyA9IHRoaXMuc2V0dGluZ3Muc3luY0ludGVydmFsO1xuICAgICAgICBpZiAoaG91cnMgPiAwICYmIHRoaXMuc2V0dGluZ3Muc2VydmVyVXJsICYmIHRoaXMuc2V0dGluZ3MuYXBpVG9rZW4pIHtcbiAgICAgICAgICAgIHRoaXMuX2ludGVydmFsSGFuZGxlID0gd2luZG93LnNldEludGVydmFsKCgpID0+IHtcbiAgICAgICAgICAgICAgICB0aGlzLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgICAgICB9LCBob3VycyAqIDM2MDAwMDApO1xuICAgICAgICB9XG4gICAgfVxuXG4gICAgYXN5bmMgbG9hZFNldHRpbmdzKCkge1xuICAgICAgICB0aGlzLnNldHRpbmdzID0gT2JqZWN0LmFzc2lnbih7fSwgREVGQVVMVF9TRVRUSU5HUywgYXdhaXQgdGhpcy5sb2FkRGF0YSgpKTtcbiAgICB9XG5cbiAgICBhc3luYyBzYXZlU2V0dGluZ3MoKSB7XG4gICAgICAgIGF3YWl0IHRoaXMuc2F2ZURhdGEodGhpcy5zZXR0aW5ncyk7XG4gICAgfVxuXG4gICAgYXN5bmMgc3luY0hpZ2hsaWdodHMoKSB7XG4gICAgICAgIC8vIFZhbGlkYXRlIHNldHRpbmdzXG4gICAgICAgIGlmICghdGhpcy5zZXR0aW5ncy5zZXJ2ZXJVcmwgfHwgIXRoaXMuc2V0dGluZ3MuYXBpVG9rZW4pIHtcbiAgICAgICAgICAgIG5ldyBOb3RpY2UoJ+KaoO+4jyBDb21tb25wbGFjZTogQ29uZmlndXJlIHNlcnZlciBVUkwgYW5kIEFQSSB0b2tlbiBpbiBTZXR0aW5ncyBmaXJzdCcpO1xuICAgICAgICAgICAgcmV0dXJuO1xuICAgICAgICB9XG5cbiAgICAgICAgbmV3IE5vdGljZSgn8J+UhCBTeW5jaW5nIGZyb20gQ29tbW9ucGxhY2UuLi4nKTtcbiAgICAgICAgY29uc3Qgc2VydmVyVXJsID0gdGhpcy5zZXR0aW5ncy5zZXJ2ZXJVcmwucmVwbGFjZSgvXFwvKyQvLCAnJyk7XG4gICAgICAgIGNvbnN0IHNpbmNlID0gdGhpcy5zZXR0aW5ncy5sYXN0U3luYyB8fCAnJztcblxuICAgICAgICB0cnkge1xuICAgICAgICAgICAgY29uc3QgdXJsID0gYCR7c2VydmVyVXJsfS9hcGkvZXhwb3J0JHtzaW5jZSA/ICc/c2luY2U9JyArIGVuY29kZVVSSUNvbXBvbmVudChzaW5jZSkgOiAnJ31gO1xuICAgICAgICAgICAgY29uc3QgcmVzcG9uc2UgPSBhd2FpdCByZXF1ZXN0VXJsKHtcbiAgICAgICAgICAgICAgICB1cmw6IHVybCxcbiAgICAgICAgICAgICAgICBtZXRob2Q6ICdHRVQnLFxuICAgICAgICAgICAgICAgIGhlYWRlcnM6IHtcbiAgICAgICAgICAgICAgICAgICAgJ0F1dGhvcml6YXRpb24nOiBgVG9rZW4gJHt0aGlzLnNldHRpbmdzLmFwaVRva2VufWAsXG4gICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgIH0pO1xuXG4gICAgICAgICAgICBpZiAocmVzcG9uc2Uuc3RhdHVzICE9PSAyMDApIHtcbiAgICAgICAgICAgICAgICBuZXcgTm90aWNlKGDimqDvuI8gQ29tbW9ucGxhY2Ugc3luYyBmYWlsZWQ6IEhUVFAgJHtyZXNwb25zZS5zdGF0dXN9YCk7XG4gICAgICAgICAgICAgICAgcmV0dXJuO1xuICAgICAgICAgICAgfVxuXG4gICAgICAgICAgICBjb25zdCBkYXRhOiBFeHBvcnRSZXNwb25zZSA9IHJlc3BvbnNlLmpzb247XG4gICAgICAgICAgICBhd2FpdCB0aGlzLndyaXRlSGlnaGxpZ2h0cyhkYXRhKTtcblxuICAgICAgICAgICAgLy8gVXBkYXRlIGxhc3Qgc3luYyB0aW1lc3RhbXBcbiAgICAgICAgICAgIHRoaXMuc2V0dGluZ3MubGFzdFN5bmMgPSBuZXcgRGF0ZSgpLnRvSVNPU3RyaW5nKCk7XG4gICAgICAgICAgICBhd2FpdCB0aGlzLnNhdmVTZXR0aW5ncygpO1xuXG4gICAgICAgICAgICBuZXcgTm90aWNlKGDinIUgQ29tbW9ucGxhY2U6IFN5bmNlZCAke2RhdGEudG90YWx9IGhpZ2hsaWdodHMgZnJvbSAke2RhdGEudG90YWxfYm9va3N9IGJvb2tzYCk7XG4gICAgICAgIH0gY2F0Y2ggKGUpIHtcbiAgICAgICAgICAgIG5ldyBOb3RpY2UoYOKaoO+4jyBDb21tb25wbGFjZSBzeW5jIGVycm9yOiAke2UubWVzc2FnZSB8fCBlfWApO1xuICAgICAgICB9XG4gICAgfVxuXG4gICAgYXN5bmMgd3JpdGVIaWdobGlnaHRzKGRhdGE6IEV4cG9ydFJlc3BvbnNlKSB7XG4gICAgICAgIC8vIEVuc3VyZSB0aGUgb3V0cHV0IGZvbGRlciBleGlzdHNcbiAgICAgICAgY29uc3QgZm9sZGVyUGF0aCA9IHRoaXMuc2V0dGluZ3Mub3V0cHV0Rm9sZGVyIHx8ICdDb21tb25wbGFjZSc7XG4gICAgICAgIGNvbnN0IGZvbGRlciA9IHRoaXMuYXBwLnZhdWx0LmdldEFic3RyYWN0RmlsZUJ5UGF0aChmb2xkZXJQYXRoKTtcbiAgICAgICAgaWYgKCFmb2xkZXIpIHtcbiAgICAgICAgICAgIGF3YWl0IHRoaXMuYXBwLnZhdWx0LmNyZWF0ZUZvbGRlcihmb2xkZXJQYXRoKTtcbiAgICAgICAgfVxuXG4gICAgICAgIGZvciAoY29uc3QgYm9vayBvZiBkYXRhLmJvb2tzKSB7XG4gICAgICAgICAgICBjb25zdCBzYWZlRmlsZU5hbWUgPSB0aGlzLnNhbml0aXplRmlsZU5hbWUoYCR7Ym9vay50aXRsZX0ubWRgKTtcbiAgICAgICAgICAgIGNvbnN0IGZpbGVQYXRoID0gYCR7Zm9sZGVyUGF0aH0vJHtzYWZlRmlsZU5hbWV9YDtcblxuICAgICAgICAgICAgLy8gQnVpbGQgbWFya2Rvd24gY29udGVudCBtYXRjaGluZyBSZWFkd2lzZSBmb3JtYXRcbiAgICAgICAgICAgIGNvbnN0IGNvbnRlbnQgPSB0aGlzLmJ1aWxkTWFya2Rvd24oYm9vayk7XG5cbiAgICAgICAgICAgIC8vIFdyaXRlIG9yIHVwZGF0ZSB0aGUgZmlsZVxuICAgICAgICAgICAgY29uc3QgZXhpc3RpbmcgPSB0aGlzLmFwcC52YXVsdC5nZXRBYnN0cmFjdEZpbGVCeVBhdGgoZmlsZVBhdGgpO1xuICAgICAgICAgICAgaWYgKGV4aXN0aW5nKSB7XG4gICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5hcHAudmF1bHQubW9kaWZ5KGV4aXN0aW5nIGFzIGFueSwgY29udGVudCk7XG4gICAgICAgICAgICB9IGVsc2Uge1xuICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMuYXBwLnZhdWx0LmNyZWF0ZShmaWxlUGF0aCwgY29udGVudCk7XG4gICAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICB9XG5cbiAgICBidWlsZE1hcmtkb3duKGJvb2s6IEJvb2tEYXRhKTogc3RyaW5nIHtcbiAgICAgICAgY29uc3QgbGluZXM6IHN0cmluZ1tdID0gW107XG4gICAgICAgIGxpbmVzLnB1c2goYCMgJHtib29rLnRpdGxlfWApO1xuICAgICAgICBsaW5lcy5wdXNoKCcnKTtcbiAgICAgICAgbGluZXMucHVzaCgnIyMgTWV0YWRhdGEnKTtcbiAgICAgICAgaWYgKGJvb2suYXV0aG9yKSB7XG4gICAgICAgICAgICBsaW5lcy5wdXNoKGAtIEF1dGhvcjogW1ske2Jvb2suYXV0aG9yfV1dYCk7XG4gICAgICAgIH1cbiAgICAgICAgbGluZXMucHVzaChgLSBGdWxsIFRpdGxlOiAke2Jvb2sudGl0bGV9YCk7XG4gICAgICAgIGxpbmVzLnB1c2goJy0gQ2F0ZWdvcnk6ICNib29rcycpO1xuICAgICAgICBsaW5lcy5wdXNoKCcnKTtcbiAgICAgICAgbGluZXMucHVzaCgnIyMgSGlnaGxpZ2h0cycpO1xuICAgICAgICBsaW5lcy5wdXNoKCcnKTtcblxuICAgICAgICBmb3IgKGNvbnN0IGggb2YgYm9vay5oaWdobGlnaHRzKSB7XG4gICAgICAgICAgICBjb25zdCBwYWdlU3RyID0gaC5wYWdlID8gYCAocC4gJHtoLnBhZ2V9KWAgOiAnJztcbiAgICAgICAgICAgIGxpbmVzLnB1c2goYC0gJHtoLnRleHR9JHtwYWdlU3RyfWApO1xuICAgICAgICAgICAgaWYgKGgudGFncyAmJiBoLnRhZ3MubGVuZ3RoID4gMCkge1xuICAgICAgICAgICAgICAgIGNvbnN0IHRhZ1N0ciA9IGgudGFncy5tYXAodCA9PiBgW1ske3R9XV1gKS5qb2luKCcgJyk7XG4gICAgICAgICAgICAgICAgbGluZXMucHVzaChgICAgIC0gVGFnczogJHt0YWdTdHJ9YCk7XG4gICAgICAgICAgICB9XG4gICAgICAgICAgICBpZiAoaC5ub3RlKSB7XG4gICAgICAgICAgICAgICAgbGluZXMucHVzaChgICAgIC0gKipOb3RlOioqICR7aC5ub3RlfWApO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgbGluZXMucHVzaCgnJyk7XG4gICAgICAgIH1cblxuICAgICAgICByZXR1cm4gbGluZXMuam9pbignXFxuJyk7XG4gICAgfVxuXG4gICAgc2FuaXRpemVGaWxlTmFtZShuYW1lOiBzdHJpbmcpOiBzdHJpbmcge1xuICAgICAgICByZXR1cm4gbmFtZS5yZXBsYWNlKC9bXFxcXC86Kj9cIjw+fF0vZywgJy0nKS5yZXBsYWNlKC9cXHMrL2csICcgJyk7XG4gICAgfVxufVxuXG5jbGFzcyBDb21tb25wbGFjZVNldHRpbmdUYWIgZXh0ZW5kcyBQbHVnaW5TZXR0aW5nVGFiIHtcbiAgICBwbHVnaW46IENvbW1vbnBsYWNlUGx1Z2luO1xuXG4gICAgY29uc3RydWN0b3IoYXBwOiBBcHAsIHBsdWdpbjogQ29tbW9ucGxhY2VQbHVnaW4pIHtcbiAgICAgICAgc3VwZXIoYXBwLCBwbHVnaW4pO1xuICAgICAgICB0aGlzLnBsdWdpbiA9IHBsdWdpbjtcbiAgICB9XG5cbiAgICBkaXNwbGF5KCk6IHZvaWQge1xuICAgICAgICBjb25zdCB7IGNvbnRhaW5lckVsIH0gPSB0aGlzO1xuICAgICAgICBjb250YWluZXJFbC5lbXB0eSgpO1xuXG4gICAgICAgIGNvbnRhaW5lckVsLmNyZWF0ZUVsKCdoMicsIHsgdGV4dDogJ0NvbW1vbnBsYWNlIFN5bmMgU2V0dGluZ3MnIH0pO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ1NlcnZlciBVUkwnKVxuICAgICAgICAgICAgLnNldERlc2MoJ1lvdXIgQ29tbW9ucGxhY2Ugc2VydmVyIFVSTCAoZS5nLiBodHRwczovL2NvbW1vbnBsYWNlLnlvdXJkb21haW4uY29tKScpXG4gICAgICAgICAgICAuYWRkVGV4dCh0ZXh0ID0+IHRleHRcbiAgICAgICAgICAgICAgICAuc2V0UGxhY2Vob2xkZXIoJ2h0dHBzOi8vLi4uJylcbiAgICAgICAgICAgICAgICAuc2V0VmFsdWUodGhpcy5wbHVnaW4uc2V0dGluZ3Muc2VydmVyVXJsKVxuICAgICAgICAgICAgICAgIC5vbkNoYW5nZShhc3luYyAodmFsdWUpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dGluZ3Muc2VydmVyVXJsID0gdmFsdWU7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR1cEludGVydmFsKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ0FQSSBUb2tlbicpXG4gICAgICAgICAgICAuc2V0RGVzYygnQVBJIHRva2VuIGZyb20gQ29tbW9ucGxhY2UgU2V0dGluZ3MgcGFnZScpXG4gICAgICAgICAgICAuYWRkVGV4dCh0ZXh0ID0+IHRleHRcbiAgICAgICAgICAgICAgICAuc2V0UGxhY2Vob2xkZXIoJ3lvdXItdG9rZW4nKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5hcGlUb2tlbilcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLmFwaVRva2VuID0gdmFsdWU7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR1cEludGVydmFsKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ091dHB1dCBGb2xkZXInKVxuICAgICAgICAgICAgLnNldERlc2MoJ0ZvbGRlciBpbiB5b3VyIHZhdWx0IHdoZXJlIGhpZ2hsaWdodCBub3RlcyB3aWxsIGJlIHNhdmVkJylcbiAgICAgICAgICAgIC5hZGRUZXh0KHRleHQgPT4gdGV4dFxuICAgICAgICAgICAgICAgIC5zZXRQbGFjZWhvbGRlcignQ29tbW9ucGxhY2UnKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5vdXRwdXRGb2xkZXIpXG4gICAgICAgICAgICAgICAgLm9uQ2hhbmdlKGFzeW5jICh2YWx1ZSkgPT4ge1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR0aW5ncy5vdXRwdXRGb2xkZXIgPSB2YWx1ZTtcbiAgICAgICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5wbHVnaW4uc2F2ZVNldHRpbmdzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ0F1dG8tc3luYyBvbiBzdGFydHVwJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdBdXRvbWF0aWNhbGx5IHN5bmMgaGlnaGxpZ2h0cyB3aGVuIE9ic2lkaWFuIG9wZW5zJylcbiAgICAgICAgICAgIC5hZGRUb2dnbGUodG9nZ2xlID0+IHRvZ2dsZVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5hdXRvU3luYylcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLmF1dG9TeW5jID0gdmFsdWU7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgIH0pKTtcblxuICAgICAgICBuZXcgU2V0dGluZyhjb250YWluZXJFbClcbiAgICAgICAgICAgIC5zZXROYW1lKCdTeW5jIGludGVydmFsJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdIb3cgb2Z0ZW4gdG8gYXV0by1zeW5jIHdoaWxlIE9ic2lkaWFuIGlzIG9wZW4gKGhvdXJzLCAwID0gb2ZmKScpXG4gICAgICAgICAgICAuYWRkU2xpZGVyKHNsaWRlciA9PiBzbGlkZXJcbiAgICAgICAgICAgICAgICAuc2V0TGltaXRzKDAsIDI0LCAxKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5zeW5jSW50ZXJ2YWwpXG4gICAgICAgICAgICAgICAgLnNldER5bmFtaWNUb29sdGlwKClcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLnN5bmNJbnRlcnZhbCA9IHZhbHVlO1xuICAgICAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLnBsdWdpbi5zYXZlU2V0dGluZ3MoKTtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dXBJbnRlcnZhbCgpO1xuICAgICAgICAgICAgICAgIH0pKTtcblxuICAgICAgICBuZXcgU2V0dGluZyhjb250YWluZXJFbClcbiAgICAgICAgICAgIC5zZXROYW1lKCdMYXN0IFN5bmMnKVxuICAgICAgICAgICAgLnNldERlc2ModGhpcy5wbHVnaW4uc2V0dGluZ3MubGFzdFN5bmNcbiAgICAgICAgICAgICAgICA/IGBMYXN0IHN5bmNlZDogJHt0aGlzLnBsdWdpbi5zZXR0aW5ncy5sYXN0U3luY31gXG4gICAgICAgICAgICAgICAgOiAnTm8gc3luYyB5ZXQnKVxuICAgICAgICAgICAgLmFkZEJ1dHRvbihidG4gPT4gYnRuXG4gICAgICAgICAgICAgICAgLnNldEJ1dHRvblRleHQoJ1N5bmMgTm93JylcbiAgICAgICAgICAgICAgICAub25DbGljaygoKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIGNvbnRhaW5lckVsLmNyZWF0ZUVsKCdocicpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ1N5bmMgQWxsJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdDbGVhciB0aGUgbGFzdCBzeW5jIHRpbWVzdGFtcCBhbmQgcHVsbCBldmVyeXRoaW5nIGFnYWluJylcbiAgICAgICAgICAgIC5hZGRCdXR0b24oYnRuID0+IGJ0blxuICAgICAgICAgICAgICAgIC5zZXRCdXR0b25UZXh0KCdSZXNldCBhbmQgU3luYyBBbGwnKVxuICAgICAgICAgICAgICAgIC5zZXRXYXJuaW5nKClcbiAgICAgICAgICAgICAgICAub25DbGljayhhc3luYyAoKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLmxhc3RTeW5jID0gJyc7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgICAgICB0aGlzLmRpc3BsYXkoKTtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc3luY0hpZ2hsaWdodHMoKTtcbiAgICAgICAgICAgICAgICB9KSk7XG4gICAgfVxufVxuIl19