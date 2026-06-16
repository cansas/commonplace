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
};
class CommonplacePlugin extends obsidian_1.Plugin {
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
        });
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoibWFpbi5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbIm1haW4udHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7QUFBQSx1Q0FBc0Y7QUFVdEYsTUFBTSxnQkFBZ0IsR0FBd0I7SUFDMUMsU0FBUyxFQUFFLEVBQUU7SUFDYixRQUFRLEVBQUUsRUFBRTtJQUNaLFlBQVksRUFBRSxhQUFhO0lBQzNCLFFBQVEsRUFBRSxFQUFFO0lBQ1osUUFBUSxFQUFFLElBQUk7Q0FDakIsQ0FBQztBQTJCRixNQUFxQixpQkFBa0IsU0FBUSxpQkFBTTtJQUczQyxNQUFNOztZQUNSLE1BQU0sSUFBSSxDQUFDLFlBQVksRUFBRSxDQUFDO1lBRTFCLDRCQUE0QjtZQUM1QixJQUFJLENBQUMsYUFBYSxDQUFDLElBQUkscUJBQXFCLENBQUMsSUFBSSxDQUFDLEdBQUcsRUFBRSxJQUFJLENBQUMsQ0FBQyxDQUFDO1lBRTlELDRCQUE0QjtZQUM1QixJQUFJLENBQUMsVUFBVSxDQUFDO2dCQUNaLEVBQUUsRUFBRSx1QkFBdUI7Z0JBQzNCLElBQUksRUFBRSxrQ0FBa0M7Z0JBQ3hDLFFBQVEsRUFBRSxHQUFHLEVBQUUsQ0FBQyxJQUFJLENBQUMsY0FBYyxFQUFFO2FBQ3hDLENBQUMsQ0FBQztZQUVILHlCQUF5QjtZQUN6QixJQUFJLENBQUMsYUFBYSxDQUFDLFVBQVUsRUFBRSx1QkFBdUIsRUFBRSxHQUFHLEVBQUU7Z0JBQ3pELElBQUksQ0FBQyxjQUFjLEVBQUUsQ0FBQztZQUMxQixDQUFDLENBQUMsQ0FBQztZQUVILHFDQUFxQztZQUNyQyxJQUFJLElBQUksQ0FBQyxRQUFRLENBQUMsUUFBUSxFQUFFLENBQUM7Z0JBQ3pCLElBQUksQ0FBQyxjQUFjLEVBQUUsQ0FBQztZQUMxQixDQUFDO1FBQ0wsQ0FBQztLQUFBO0lBRUssWUFBWTs7WUFDZCxJQUFJLENBQUMsUUFBUSxHQUFHLE1BQU0sQ0FBQyxNQUFNLENBQUMsRUFBRSxFQUFFLGdCQUFnQixFQUFFLE1BQU0s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bkIsT0FBTyxDQUFDLFdBQVcsQ0FBQzthQUNwQixPQUFPLENBQUMsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUTtZQUNsQyxDQUFDLENBQUMsZ0JBQWdCLElBQUksQ0FBQyxNQUFNLENBQUMsUUFBUSxDQUFDLFFBQVEsRUFBRTtZQUNqRCxDQUFDLENBQUMsYUFBYSxDQUFDO2FBQ25CLFNBQVMsQ0FBQyxHQUFHLENBQUMsRUFBRSxDQUFDLEdBQUc7YUFDaEIsYUFBYSxDQUFDLFVBQVUsQ0FBQzthQUN6QixPQUFPLENBQUMsR0FBRyxFQUFFO1lBQ1YsSUFBSSxDQUFDLE1BQU0sQ0FBQyxjQUFjLEVBQUUsQ0FBQztRQUNqQyxDQUFDLENBQUMsQ0FBQyxDQUFDO1FBRVosV0FBVyxDQUFDLFFBQVEsQ0FBQyxJQUFJLENBQUMsQ0FBQztRQUUzQixJQUFJLGtCQUFPLENBQUMsV0FBVyxDQUFDO2FBQ25CLE9BQU8sQ0FBQyxVQUFVLENBQUM7YUFDbkIsT0FBTyxDQUFDLHlEQUF5RCxDQUFDO2FBQ2xFLFNBQVMsQ0FBQyxHQUFHLENBQUMsRUFBRSxDQUFDLEdBQUc7YUFDaEIsYUFBYSxDQUFDLG9CQUFvQixDQUFDO2FBQ25DLFVBQVUsRUFBRTthQUNaLE9BQU8sQ0FBQyxHQUFTLEVBQUU7WUFDaEIsSUFBSSxDQUFDLE1BQU0sQ0FBQyxRQUFRLENBQUMsUUFBUSxHQUFHLEVBQUUsQ0FBQztZQUNuQyxNQUFNLElBQUksQ0FBQyxNQUFNLENBQUMsWUFBWSxFQUFFLENBQUM7WUFDakMsSUFBSSxDQUFDLE9BQU8sRUFBRSxDQUFDO1lBQ2YsSUFBSSxDQUFDLE1BQU0sQ0FBQyxjQUFjLEVBQUUsQ0FBQztRQUNqQyxDQUFDLENBQUEsQ0FBQyxDQUFDLENBQUM7SUFDaEIsQ0FBQztDQUNKIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0IHsgQXBwLCBQbHVnaW4sIFBsdWdpblNldHRpbmdUYWIsIFNldHRpbmcsIE5vdGljZSwgcmVxdWVzdFVybCB9IGZyb20gJ29ic2lkaWFuJztcblxuaW50ZXJmYWNlIENvbW1vbnBsYWNlU2V0dGluZ3Mge1xuICAgIHNlcnZlclVybDogc3RyaW5nO1xuICAgIGFwaVRva2VuOiBzdHJpbmc7XG4gICAgb3V0cHV0Rm9sZGVyOiBzdHJpbmc7XG4gICAgbGFzdFN5bmM6IHN0cmluZztcbiAgICBhdXRvU3luYzogYm9vbGVhbjtcbn1cblxuY29uc3QgREVGQVVMVF9TRVRUSU5HUzogQ29tbW9ucGxhY2VTZXR0aW5ncyA9IHtcbiAgICBzZXJ2ZXJVcmw6ICcnLFxuICAgIGFwaVRva2VuOiAnJyxcbiAgICBvdXRwdXRGb2xkZXI6ICdDb21tb25wbGFjZScsXG4gICAgbGFzdFN5bmM6ICcnLFxuICAgIGF1dG9TeW5jOiB0cnVlLFxufTtcblxuaW50ZXJmYWNlIEhpZ2hsaWdodERhdGEge1xuICAgIGlkOiBudW1iZXI7XG4gICAgdGV4dDogc3RyaW5nO1xuICAgIG5vdGU6IHN0cmluZyB8IG51bGw7XG4gICAgcGFnZTogbnVtYmVyIHwgbnVsbDtcbiAgICBjaGFwdGVyOiBzdHJpbmcgfCBudWxsO1xuICAgIGNvbG9yOiBzdHJpbmcgfCBudWxsO1xuICAgIGZhdm9yaXRlOiBib29sZWFuO1xuICAgIGhpZ2hsaWdodGVkX2F0OiBzdHJpbmcgfCBudWxsO1xuICAgIGNyZWF0ZWRfYXQ6IHN0cmluZyB8IG51bGw7XG4gICAgdGFnczogc3RyaW5nW107XG59XG5cbmludGVyZmFjZSBCb29rRGF0YSB7XG4gICAgdGl0bGU6IHN0cmluZztcbiAgICBhdXRob3I6IHN0cmluZztcbiAgICBoaWdobGlnaHRzOiBIaWdobGlnaHREYXRhW107XG59XG5cbmludGVyZmFjZSBFeHBvcnRSZXNwb25zZSB7XG4gICAgYm9va3M6IEJvb2tEYXRhW107XG4gICAgdG90YWw6IG51bWJlcjtcbiAgICB0b3RhbF9ib29rczogbnVtYmVyO1xufVxuXG5leHBvcnQgZGVmYXVsdCBjbGFzcyBDb21tb25wbGFjZVBsdWdpbiBleHRlbmRzIFBsdWdpbiB7XG4gICAgc2V0dGluZ3M6IENvbW1vbnBsYWNlU2V0dGluZ3M7XG5cbiAgICBhc3luYyBvbmxvYWQoKSB7XG4gICAgICAgIGF3YWl0IHRoaXMubG9hZFNldHRpbmdzKCk7XG5cbiAgICAgICAgLy8gUmVnaXN0ZXIgdGhlIHNldHRpbmdzIHRhYlxuICAgICAgICB0aGlzLmFkZFNldHRpbmdUYWIobmV3IENvbW1vbnBsYWNlU2V0dGluZ1RhYih0aGlzLmFwcCwgdGhpcykpO1xuXG4gICAgICAgIC8vIFJlZ2lzdGVyIHRoZSBzeW5jIGNvbW1hbmRcbiAgICAgICAgdGhpcy5hZGRDb21tYW5kKHtcbiAgICAgICAgICAgIGlkOiAnc3luYy1mcm9tLWNvbW1vbnBsYWNlJyxcbiAgICAgICAgICAgIG5hbWU6ICdTeW5jIGhpZ2hsaWdodHMgZnJvbSBDb21tb25wbGFjZScsXG4gICAgICAgICAgICBjYWxsYmFjazogKCkgPT4gdGhpcy5zeW5jSGlnaGxpZ2h0cygpLFxuICAgICAgICB9KTtcblxuICAgICAgICAvLyBBbHNvIGFkZCBhIHJpYmJvbiBpY29uXG4gICAgICAgIHRoaXMuYWRkUmliYm9uSWNvbignZG93bmxvYWQnLCAnU3luYyBmcm9tIENvbW1vbnBsYWNlJywgKCkgPT4ge1xuICAgICAgICAgICAgdGhpcy5zeW5jSGlnaGxpZ2h0cygpO1xuICAgICAgICB9KTtcblxuICAgICAgICAvLyBBdXRvLXN5bmMgb24gc3RhcnR1cCBpZiBjb25maWd1cmVkXG4gICAgICAgIGlmICh0aGlzLnNldHRpbmdzLmF1dG9TeW5jKSB7XG4gICAgICAgICAgICB0aGlzLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgIH1cbiAgICB9XG5cbiAgICBhc3luYyBsb2FkU2V0dGluZ3MoKSB7XG4gICAgICAgIHRoaXMuc2V0dGluZ3MgPSBPYmplY3QuYXNzaWduKHt9LCBERUZBVUxUX1NFVFRJTkdTLCBhd2FpdCB0aGlzLmxvYWREYXRhKCkpO1xuICAgIH1cblxuICAgIGFzeW5jIHNhdmVTZXR0aW5ncygpIHtcbiAgICAgICAgYXdhaXQgdGhpcy5zYXZlRGF0YSh0aGlzLnNldHRpbmdzKTtcbiAgICB9XG5cbiAgICBhc3luYyBzeW5jSGlnaGxpZ2h0cygpIHtcbiAgICAgICAgLy8gVmFsaWRhdGUgc2V0dGluZ3NcbiAgICAgICAgaWYgKCF0aGlzLnNldHRpbmdzLnNlcnZlclVybCB8fCAhdGhpcy5zZXR0aW5ncy5hcGlUb2tlbikge1xuICAgICAgICAgICAgbmV3IE5vdGljZSgn4pqg77iPIENvbW1vbnBsYWNlOiBDb25maWd1cmUgc2VydmVyIFVSTCBhbmQgQVBJIHRva2VuIGluIFNldHRpbmdzIGZpcnN0Jyk7XG4gICAgICAgICAgICByZXR1cm47XG4gICAgICAgIH1cblxuICAgICAgICBuZXcgTm90aWNlKCfwn5SEIFN5bmNpbmcgZnJvbSBDb21tb25wbGFjZS4uLicpO1xuICAgICAgICBjb25zdCBzZXJ2ZXJVcmwgPSB0aGlzLnNldHRpbmdzLnNlcnZlclVybC5yZXBsYWNlKC9cXC8rJC8sICcnKTtcbiAgICAgICAgY29uc3Qgc2luY2UgPSB0aGlzLnNldHRpbmdzLmxhc3RTeW5jIHx8ICcnO1xuXG4gICAgICAgIHRyeSB7XG4gICAgICAgICAgICBjb25zdCB1cmwgPSBgJHtzZXJ2ZXJVcmx9L2FwaS9leHBvcnQke3NpbmNlID8gJz9zaW5jZT0nICsgZW5jb2RlVVJJQ29tcG9uZW50KHNpbmNlKSA6ICcnfWA7XG4gICAgICAgICAgICBjb25zdCByZXNwb25zZSA9IGF3YWl0IHJlcXVlc3RVcmwoe1xuICAgICAgICAgICAgICAgIHVybDogdXJsLFxuICAgICAgICAgICAgICAgIG1ldGhvZDogJ0dFVCcsXG4gICAgICAgICAgICAgICAgaGVhZGVyczoge1xuICAgICAgICAgICAgICAgICAgICAnQXV0aG9yaXphdGlvbic6IGBUb2tlbiAke3RoaXMuc2V0dGluZ3MuYXBpVG9rZW59YCxcbiAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgfSk7XG5cbiAgICAgICAgICAgIGlmIChyZXNwb25zZS5zdGF0dXMgIT09IDIwMCkge1xuICAgICAgICAgICAgICAgIG5ldyBOb3RpY2UoYOKaoO+4jyBDb21tb25wbGFjZSBzeW5jIGZhaWxlZDogSFRUUCAke3Jlc3BvbnNlLnN0YXR1c31gKTtcbiAgICAgICAgICAgICAgICByZXR1cm47XG4gICAgICAgICAgICB9XG5cbiAgICAgICAgICAgIGNvbnN0IGRhdGE6IEV4cG9ydFJlc3BvbnNlID0gcmVzcG9uc2UuanNvbjtcbiAgICAgICAgICAgIGF3YWl0IHRoaXMud3JpdGVIaWdobGlnaHRzKGRhdGEpO1xuXG4gICAgICAgICAgICAvLyBVcGRhdGUgbGFzdCBzeW5jIHRpbWVzdGFtcFxuICAgICAgICAgICAgdGhpcy5zZXR0aW5ncy5sYXN0U3luYyA9IG5ldyBEYXRlKCkudG9JU09TdHJpbmcoKTtcbiAgICAgICAgICAgIGF3YWl0IHRoaXMuc2F2ZVNldHRpbmdzKCk7XG5cbiAgICAgICAgICAgIG5ldyBOb3RpY2UoYOKchSBDb21tb25wbGFjZTogU3luY2VkICR7ZGF0YS50b3RhbH0gaGlnaGxpZ2h0cyBmcm9tICR7ZGF0YS50b3RhbF9ib29rc30gYm9va3NgKTtcbiAgICAgICAgfSBjYXRjaCAoZSkge1xuICAgICAgICAgICAgbmV3IE5vdGljZShg4pqg77iPIENvbW1vbnBsYWNlIHN5bmMgZXJyb3I6ICR7ZS5tZXNzYWdlIHx8IGV9YCk7XG4gICAgICAgIH1cbiAgICB9XG5cbiAgICBhc3luYyB3cml0ZUhpZ2hsaWdodHMoZGF0YTogRXhwb3J0UmVzcG9uc2UpIHtcbiAgICAgICAgLy8gRW5zdXJlIHRoZSBvdXRwdXQgZm9sZGVyIGV4aXN0c1xuICAgICAgICBjb25zdCBmb2xkZXJQYXRoID0gdGhpcy5zZXR0aW5ncy5vdXRwdXRGb2xkZXIgfHwgJ0NvbW1vbnBsYWNlJztcbiAgICAgICAgY29uc3QgZm9sZGVyID0gdGhpcy5hcHAudmF1bHQuZ2V0QWJzdHJhY3RGaWxlQnlQYXRoKGZvbGRlclBhdGgpO1xuICAgICAgICBpZiAoIWZvbGRlcikge1xuICAgICAgICAgICAgYXdhaXQgdGhpcy5hcHAudmF1bHQuY3JlYXRlRm9sZGVyKGZvbGRlclBhdGgpO1xuICAgICAgICB9XG5cbiAgICAgICAgZm9yIChjb25zdCBib29rIG9mIGRhdGEuYm9va3MpIHtcbiAgICAgICAgICAgIGNvbnN0IHNhZmVGaWxlTmFtZSA9IHRoaXMuc2FuaXRpemVGaWxlTmFtZShgJHtib29rLnRpdGxlfS5tZGApO1xuICAgICAgICAgICAgY29uc3QgZmlsZVBhdGggPSBgJHtmb2xkZXJQYXRofS8ke3NhZmVGaWxlTmFtZX1gO1xuXG4gICAgICAgICAgICAvLyBCdWlsZCBtYXJrZG93biBjb250ZW50IG1hdGNoaW5nIFJlYWR3aXNlIGZvcm1hdFxuICAgICAgICAgICAgY29uc3QgY29udGVudCA9IHRoaXMuYnVpbGRNYXJrZG93bihib29rKTtcblxuICAgICAgICAgICAgLy8gV3JpdGUgb3IgdXBkYXRlIHRoZSBmaWxlXG4gICAgICAgICAgICBjb25zdCBleGlzdGluZyA9IHRoaXMuYXBwLnZhdWx0LmdldEFic3RyYWN0RmlsZUJ5UGF0aChmaWxlUGF0aCk7XG4gICAgICAgICAgICBpZiAoZXhpc3RpbmcpIHtcbiAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLmFwcC52YXVsdC5tb2RpZnkoZXhpc3RpbmcgYXMgYW55LCBjb250ZW50KTtcbiAgICAgICAgICAgIH0gZWxzZSB7XG4gICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5hcHAudmF1bHQuY3JlYXRlKGZpbGVQYXRoLCBjb250ZW50KTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgIH1cblxuICAgIGJ1aWxkTWFya2Rvd24oYm9vazogQm9va0RhdGEpOiBzdHJpbmcge1xuICAgICAgICBjb25zdCBsaW5lczogc3RyaW5nW10gPSBbXTtcbiAgICAgICAgbGluZXMucHVzaChgIyAke2Jvb2sudGl0bGV9YCk7XG4gICAgICAgIGxpbmVzLnB1c2goJycpO1xuICAgICAgICBsaW5lcy5wdXNoKCcjIyBNZXRhZGF0YScpO1xuICAgICAgICBpZiAoYm9vay5hdXRob3IpIHtcbiAgICAgICAgICAgIGxpbmVzLnB1c2goYC0gQXV0aG9yOiBbWyR7Ym9vay5hdXRob3J9XV1gKTtcbiAgICAgICAgfVxuICAgICAgICBsaW5lcy5wdXNoKGAtIEZ1bGwgVGl0bGU6ICR7Ym9vay50aXRsZX1gKTtcbiAgICAgICAgbGluZXMucHVzaCgnLSBDYXRlZ29yeTogI2Jvb2tzJyk7XG4gICAgICAgIGxpbmVzLnB1c2goJycpO1xuICAgICAgICBsaW5lcy5wdXNoKCcjIyBIaWdobGlnaHRzJyk7XG4gICAgICAgIGxpbmVzLnB1c2goJycpO1xuXG4gICAgICAgIGZvciAoY29uc3QgaCBvZiBib29rLmhpZ2hsaWdodHMpIHtcbiAgICAgICAgICAgIGNvbnN0IHBhZ2VTdHIgPSBoLnBhZ2UgPyBgIChwLiAke2gucGFnZX0pYCA6ICcnO1xuICAgICAgICAgICAgbGluZXMucHVzaChgLSAke2gudGV4dH0ke3BhZ2VTdHJ9YCk7XG4gICAgICAgICAgICBpZiAoaC50YWdzICYmIGgudGFncy5sZW5ndGggPiAwKSB7XG4gICAgICAgICAgICAgICAgY29uc3QgdGFnU3RyID0gaC50YWdzLm1hcCh0ID0+IGBbWyR7dH1dXWApLmpvaW4oJyAnKTtcbiAgICAgICAgICAgICAgICBsaW5lcy5wdXNoKGAgICAgLSBUYWdzOiAke3RhZ1N0cn1gKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICAgIGlmIChoLm5vdGUpIHtcbiAgICAgICAgICAgICAgICBsaW5lcy5wdXNoKGAgICAgLSAqKk5vdGU6KiogJHtoLm5vdGV9YCk7XG4gICAgICAgICAgICB9XG4gICAgICAgICAgICBsaW5lcy5wdXNoKCcnKTtcbiAgICAgICAgfVxuXG4gICAgICAgIHJldHVybiBsaW5lcy5qb2luKCdcXG4nKTtcbiAgICB9XG5cbiAgICBzYW5pdGl6ZUZpbGVOYW1lKG5hbWU6IHN0cmluZyk6IHN0cmluZyB7XG4gICAgICAgIHJldHVybiBuYW1lLnJlcGxhY2UoL1tcXFxcLzoqP1wiPD58XS9nLCAnLScpLnJlcGxhY2UoL1xccysvZywgJyAnKTtcbiAgICB9XG59XG5cbmNsYXNzIENvbW1vbnBsYWNlU2V0dGluZ1RhYiBleHRlbmRzIFBsdWdpblNldHRpbmdUYWIge1xuICAgIHBsdWdpbjogQ29tbW9ucGxhY2VQbHVnaW47XG5cbiAgICBjb25zdHJ1Y3RvcihhcHA6IEFwcCwgcGx1Z2luOiBDb21tb25wbGFjZVBsdWdpbikge1xuICAgICAgICBzdXBlcihhcHAsIHBsdWdpbik7XG4gICAgICAgIHRoaXMucGx1Z2luID0gcGx1Z2luO1xuICAgIH1cblxuICAgIGRpc3BsYXkoKTogdm9pZCB7XG4gICAgICAgIGNvbnN0IHsgY29udGFpbmVyRWwgfSA9IHRoaXM7XG4gICAgICAgIGNvbnRhaW5lckVsLmVtcHR5KCk7XG5cbiAgICAgICAgY29udGFpbmVyRWwuY3JlYXRlRWwoJ2gyJywgeyB0ZXh0OiAnQ29tbW9ucGxhY2UgU3luYyBTZXR0aW5ncycgfSk7XG5cbiAgICAgICAgbmV3IFNldHRpbmcoY29udGFpbmVyRWwpXG4gICAgICAgICAgICAuc2V0TmFtZSgnU2VydmVyIFVSTCcpXG4gICAgICAgICAgICAuc2V0RGVzYygnWW91ciBDb21tb25wbGFjZSBzZXJ2ZXIgVVJMIChlLmcuIGh0dHBzOi8vY29tbW9ucGxhY2UueW91cmRvbWFpbi5jb20pJylcbiAgICAgICAgICAgIC5hZGRUZXh0KHRleHQgPT4gdGV4dFxuICAgICAgICAgICAgICAgIC5zZXRQbGFjZWhvbGRlcignaHR0cHM6Ly8uLi4nKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5zZXJ2ZXJVcmwpXG4gICAgICAgICAgICAgICAgLm9uQ2hhbmdlKGFzeW5jICh2YWx1ZSkgPT4ge1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR0aW5ncy5zZXJ2ZXJVcmwgPSB2YWx1ZTtcbiAgICAgICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5wbHVnaW4uc2F2ZVNldHRpbmdzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ0FQSSBUb2tlbicpXG4gICAgICAgICAgICAuc2V0RGVzYygnQVBJIHRva2VuIGZyb20gQ29tbW9ucGxhY2UgU2V0dGluZ3MgcGFnZScpXG4gICAgICAgICAgICAuYWRkVGV4dCh0ZXh0ID0+IHRleHRcbiAgICAgICAgICAgICAgICAuc2V0UGxhY2Vob2xkZXIoJ3lvdXItdG9rZW4nKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5hcGlUb2tlbilcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLmFwaVRva2VuID0gdmFsdWU7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgIH0pKTtcblxuICAgICAgICBuZXcgU2V0dGluZyhjb250YWluZXJFbClcbiAgICAgICAgICAgIC5zZXROYW1lKCdPdXRwdXQgRm9sZGVyJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdGb2xkZXIgaW4geW91ciB2YXVsdCB3aGVyZSBoaWdobGlnaHQgbm90ZXMgd2lsbCBiZSBzYXZlZCcpXG4gICAgICAgICAgICAuYWRkVGV4dCh0ZXh0ID0+IHRleHRcbiAgICAgICAgICAgICAgICAuc2V0UGxhY2Vob2xkZXIoJ0NvbW1vbnBsYWNlJylcbiAgICAgICAgICAgICAgICAuc2V0VmFsdWUodGhpcy5wbHVnaW4uc2V0dGluZ3Mub3V0cHV0Rm9sZGVyKVxuICAgICAgICAgICAgICAgIC5vbkNoYW5nZShhc3luYyAodmFsdWUpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dGluZ3Mub3V0cHV0Rm9sZGVyID0gdmFsdWU7XG4gICAgICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMucGx1Z2luLnNhdmVTZXR0aW5ncygpO1xuICAgICAgICAgICAgICAgIH0pKTtcblxuICAgICAgICAgICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgICAgIC5zZXROYW1lKCdBdXRvLXN5bmMgb24gc3RhcnR1cCcpXG4gICAgICAgICAgICAgICAgLnNldERlc2MoJ0F1dG9tYXRpY2FsbHkgc3luYyBoaWdobGlnaHRzIHdoZW4gT2JzaWRpYW4gb3BlbnMnKVxuICAgICAgICAgICAgICAgIC5hZGRUb2dnbGUodG9nZ2xlID0+IHRvZ2dsZVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5hdXRvU3luYylcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dGluZ3MuYXV0b1N5bmMgPSB2YWx1ZTtcbiAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLnBsdWdpbi5zYXZlU2V0dGluZ3MoKTtcbiAgICAgICAgICAgICAgICB9KSk7XG5cbiAgICAgICAgbmV3IFNldHRpbmcoY29udGFpbmVyRWwpXG4gICAgICAgICAgICAuc2V0TmFtZSgnTGFzdCBTeW5jJylcbiAgICAgICAgICAgIC5zZXREZXNjKHRoaXMucGx1Z2luLnNldHRpbmdzLmxhc3RTeW5jXG4gICAgICAgICAgICAgICAgPyBgTGFzdCBzeW5jZWQ6ICR7dGhpcy5wbHVnaW4uc2V0dGluZ3MubGFzdFN5bmN9YFxuICAgICAgICAgICAgICAgIDogJ05vIHN5bmMgeWV0JylcbiAgICAgICAgICAgIC5hZGRCdXR0b24oYnRuID0+IGJ0blxuICAgICAgICAgICAgICAgIC5zZXRCdXR0b25UZXh0KCdTeW5jIE5vdycpXG4gICAgICAgICAgICAgICAgLm9uQ2xpY2soKCkgPT4ge1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zeW5jSGlnaGxpZ2h0cygpO1xuICAgICAgICAgICAgICAgIH0pKTtcblxuICAgICAgICBjb250YWluZXJFbC5jcmVhdGVFbCgnaHInKTtcblxuICAgICAgICBuZXcgU2V0dGluZyhjb250YWluZXJFbClcbiAgICAgICAgICAgIC5zZXROYW1lKCdTeW5jIEFsbCcpXG4gICAgICAgICAgICAuc2V0RGVzYygnQ2xlYXIgdGhlIGxhc3Qgc3luYyB0aW1lc3RhbXAgYW5kIHB1bGwgZXZlcnl0aGluZyBhZ2FpbicpXG4gICAgICAgICAgICAuYWRkQnV0dG9uKGJ0biA9PiBidG5cbiAgICAgICAgICAgICAgICAuc2V0QnV0dG9uVGV4dCgnUmVzZXQgYW5kIFN5bmMgQWxsJylcbiAgICAgICAgICAgICAgICAuc2V0V2FybmluZygpXG4gICAgICAgICAgICAgICAgLm9uQ2xpY2soYXN5bmMgKCkgPT4ge1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR0aW5ncy5sYXN0U3luYyA9ICcnO1xuICAgICAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLnBsdWdpbi5zYXZlU2V0dGluZ3MoKTtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5kaXNwbGF5KCk7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuICAgIH1cbn1cbiJdfQ==