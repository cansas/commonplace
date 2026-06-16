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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoibWFpbi5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbIm1haW4udHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7QUFBQSx1Q0FBc0Y7QUFTdEYsTUFBTSxnQkFBZ0IsR0FBd0I7SUFDMUMsU0FBUyxFQUFFLEVBQUU7SUFDYixRQUFRLEVBQUUsRUFBRTtJQUNaLFlBQVksRUFBRSxhQUFhO0lBQzNCLFFBQVEsRUFBRSxFQUFFO0NBQ2YsQ0FBQztBQTJCRixNQUFxQixpQkFBa0IsU0FBUSxpQkFBTTtJQUczQyxNQUFNOztZQUNSLE1BQU0sSUFBSSxDQUFDLFlBQVksRUFBRSxDQUFDO1lBRTFCLDRCQUE0QjtZQUM1QixJQUFJLENBQUMsYUFBYSxDQUFDLElBQUkscUJBQXFCLENBQUMsSUFBSSxDQUFDLEdBQUcsRUFBRSxJQUFJLENBQUMsQ0FBQyxDQUFDO1lBRTlELDRCQUE0QjtZQUM1QixJQUFJLENBQUMsVUFBVSxDQUFDO2dCQUNaLEVBQUUsRUFBRSx1QkFBdUI7Z0JBQzNCLElBQUksRUFBRSxrQ0FBa0M7Z0JBQ3hDLFFBQVEsRUFBRSxHQUFHLEVBQUUsQ0FBQyxJQUFJLENBQUMsY0FBYyxFQUFFO2FBQ3hDLENBQUMsQ0FBQztZQUVILHlCQUF5QjtZQUN6QixJQUFJLENBQUMsYUFBYSxDQUFDLFVBQVUsRUFBRSx1QkFBdUIsRUFBRSxHQUFHLEVBQUU7Z0JBQ3pELElBQUksQ0FBQyxjQUFjLEVBQUUsQ0FBQztZQUMxQixDQUFDLENBQUMsQ0FBQztRQUNQLENBQUM7S0FBQTtJQUVLLFlBQVk7O1lBQ2QsSUFBSSxDQUFDLFFBQVEsR0FBRyxNQUFNLENBQUMsTUFBTSxDQUFDLEVBQUUsRUFBRSxnQkFBZ0IsRUFBRSxNQUFNLElBQUksQ0FBQyxRQUFRLEVBQUUsQ0FBQyxDQUFDO1FBQy9FLENBQUM7S0FBQTtJQUVLLFlBQVk7O1lBQ2QsTUFBTSxJQUFJLENBQUMsUUFBUSxDQUFDLElBQUksQ0FBQyxRQUFRLENBQUMsQ0FBQztRQUN2QyxDQUFD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QUFFLENBQUMsR0FBRzthQUNoQixhQUFhLENBQUMsb0JBQW9CLENBQUM7YUFDbkMsVUFBVSxFQUFFO2FBQ1osT0FBTyxDQUFDLEdBQVMsRUFBRTtZQUNoQixJQUFJLENBQUMsTUFBTSxDQUFDLFFBQVEsQ0FBQyxRQUFRLEdBQUcsRUFBRSxDQUFDO1lBQ25DLE1BQU0sSUFBSSxDQUFDLE1BQU0sQ0FBQyxZQUFZLEVBQUUsQ0FBQztZQUNqQyxJQUFJLENBQUMsT0FBTyxFQUFFLENBQUM7WUFDZixJQUFJLENBQUMsTUFBTSxDQUFDLGNBQWMsRUFBRSxDQUFDO1FBQ2pDLENBQUMsQ0FBQSxDQUFDLENBQUMsQ0FBQztJQUNoQixDQUFDO0NBQ0oiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgeyBBcHAsIFBsdWdpbiwgUGx1Z2luU2V0dGluZ1RhYiwgU2V0dGluZywgTm90aWNlLCByZXF1ZXN0VXJsIH0gZnJvbSAnb2JzaWRpYW4nO1xuXG5pbnRlcmZhY2UgQ29tbW9ucGxhY2VTZXR0aW5ncyB7XG4gICAgc2VydmVyVXJsOiBzdHJpbmc7XG4gICAgYXBpVG9rZW46IHN0cmluZztcbiAgICBvdXRwdXRGb2xkZXI6IHN0cmluZztcbiAgICBsYXN0U3luYzogc3RyaW5nO1xufVxuXG5jb25zdCBERUZBVUxUX1NFVFRJTkdTOiBDb21tb25wbGFjZVNldHRpbmdzID0ge1xuICAgIHNlcnZlclVybDogJycsXG4gICAgYXBpVG9rZW46ICcnLFxuICAgIG91dHB1dEZvbGRlcjogJ0NvbW1vbnBsYWNlJyxcbiAgICBsYXN0U3luYzogJycsXG59O1xuXG5pbnRlcmZhY2UgSGlnaGxpZ2h0RGF0YSB7XG4gICAgaWQ6IG51bWJlcjtcbiAgICB0ZXh0OiBzdHJpbmc7XG4gICAgbm90ZTogc3RyaW5nIHwgbnVsbDtcbiAgICBwYWdlOiBudW1iZXIgfCBudWxsO1xuICAgIGNoYXB0ZXI6IHN0cmluZyB8IG51bGw7XG4gICAgY29sb3I6IHN0cmluZyB8IG51bGw7XG4gICAgZmF2b3JpdGU6IGJvb2xlYW47XG4gICAgaGlnaGxpZ2h0ZWRfYXQ6IHN0cmluZyB8IG51bGw7XG4gICAgY3JlYXRlZF9hdDogc3RyaW5nIHwgbnVsbDtcbiAgICB0YWdzOiBzdHJpbmdbXTtcbn1cblxuaW50ZXJmYWNlIEJvb2tEYXRhIHtcbiAgICB0aXRsZTogc3RyaW5nO1xuICAgIGF1dGhvcjogc3RyaW5nO1xuICAgIGhpZ2hsaWdodHM6IEhpZ2hsaWdodERhdGFbXTtcbn1cblxuaW50ZXJmYWNlIEV4cG9ydFJlc3BvbnNlIHtcbiAgICBib29rczogQm9va0RhdGFbXTtcbiAgICB0b3RhbDogbnVtYmVyO1xuICAgIHRvdGFsX2Jvb2tzOiBudW1iZXI7XG59XG5cbmV4cG9ydCBkZWZhdWx0IGNsYXNzIENvbW1vbnBsYWNlUGx1Z2luIGV4dGVuZHMgUGx1Z2luIHtcbiAgICBzZXR0aW5nczogQ29tbW9ucGxhY2VTZXR0aW5ncztcblxuICAgIGFzeW5jIG9ubG9hZCgpIHtcbiAgICAgICAgYXdhaXQgdGhpcy5sb2FkU2V0dGluZ3MoKTtcblxuICAgICAgICAvLyBSZWdpc3RlciB0aGUgc2V0dGluZ3MgdGFiXG4gICAgICAgIHRoaXMuYWRkU2V0dGluZ1RhYihuZXcgQ29tbW9ucGxhY2VTZXR0aW5nVGFiKHRoaXMuYXBwLCB0aGlzKSk7XG5cbiAgICAgICAgLy8gUmVnaXN0ZXIgdGhlIHN5bmMgY29tbWFuZFxuICAgICAgICB0aGlzLmFkZENvbW1hbmQoe1xuICAgICAgICAgICAgaWQ6ICdzeW5jLWZyb20tY29tbW9ucGxhY2UnLFxuICAgICAgICAgICAgbmFtZTogJ1N5bmMgaGlnaGxpZ2h0cyBmcm9tIENvbW1vbnBsYWNlJyxcbiAgICAgICAgICAgIGNhbGxiYWNrOiAoKSA9PiB0aGlzLnN5bmNIaWdobGlnaHRzKCksXG4gICAgICAgIH0pO1xuXG4gICAgICAgIC8vIEFsc28gYWRkIGEgcmliYm9uIGljb25cbiAgICAgICAgdGhpcy5hZGRSaWJib25JY29uKCdkb3dubG9hZCcsICdTeW5jIGZyb20gQ29tbW9ucGxhY2UnLCAoKSA9PiB7XG4gICAgICAgICAgICB0aGlzLnN5bmNIaWdobGlnaHRzKCk7XG4gICAgICAgIH0pO1xuICAgIH1cblxuICAgIGFzeW5jIGxvYWRTZXR0aW5ncygpIHtcbiAgICAgICAgdGhpcy5zZXR0aW5ncyA9IE9iamVjdC5hc3NpZ24oe30sIERFRkFVTFRfU0VUVElOR1MsIGF3YWl0IHRoaXMubG9hZERhdGEoKSk7XG4gICAgfVxuXG4gICAgYXN5bmMgc2F2ZVNldHRpbmdzKCkge1xuICAgICAgICBhd2FpdCB0aGlzLnNhdmVEYXRhKHRoaXMuc2V0dGluZ3MpO1xuICAgIH1cblxuICAgIGFzeW5jIHN5bmNIaWdobGlnaHRzKCkge1xuICAgICAgICAvLyBWYWxpZGF0ZSBzZXR0aW5nc1xuICAgICAgICBpZiAoIXRoaXMuc2V0dGluZ3Muc2VydmVyVXJsIHx8ICF0aGlzLnNldHRpbmdzLmFwaVRva2VuKSB7XG4gICAgICAgICAgICBuZXcgTm90aWNlKCfimqDvuI8gQ29tbW9ucGxhY2U6IENvbmZpZ3VyZSBzZXJ2ZXIgVVJMIGFuZCBBUEkgdG9rZW4gaW4gU2V0dGluZ3MgZmlyc3QnKTtcbiAgICAgICAgICAgIHJldHVybjtcbiAgICAgICAgfVxuXG4gICAgICAgIG5ldyBOb3RpY2UoJ/CflIQgU3luY2luZyBmcm9tIENvbW1vbnBsYWNlLi4uJyk7XG4gICAgICAgIGNvbnN0IHNlcnZlclVybCA9IHRoaXMuc2V0dGluZ3Muc2VydmVyVXJsLnJlcGxhY2UoL1xcLyskLywgJycpO1xuICAgICAgICBjb25zdCBzaW5jZSA9IHRoaXMuc2V0dGluZ3MubGFzdFN5bmMgfHwgJyc7XG5cbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICAgIGNvbnN0IHVybCA9IGAke3NlcnZlclVybH0vYXBpL2V4cG9ydCR7c2luY2UgPyAnP3NpbmNlPScgKyBlbmNvZGVVUklDb21wb25lbnQoc2luY2UpIDogJyd9YDtcbiAgICAgICAgICAgIGNvbnN0IHJlc3BvbnNlID0gYXdhaXQgcmVxdWVzdFVybCh7XG4gICAgICAgICAgICAgICAgdXJsOiB1cmwsXG4gICAgICAgICAgICAgICAgbWV0aG9kOiAnR0VUJyxcbiAgICAgICAgICAgICAgICBoZWFkZXJzOiB7XG4gICAgICAgICAgICAgICAgICAgICdBdXRob3JpemF0aW9uJzogYFRva2VuICR7dGhpcy5zZXR0aW5ncy5hcGlUb2tlbn1gLFxuICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICB9KTtcblxuICAgICAgICAgICAgaWYgKHJlc3BvbnNlLnN0YXR1cyAhPT0gMjAwKSB7XG4gICAgICAgICAgICAgICAgbmV3IE5vdGljZShg4pqg77iPIENvbW1vbnBsYWNlIHN5bmMgZmFpbGVkOiBIVFRQICR7cmVzcG9uc2Uuc3RhdHVzfWApO1xuICAgICAgICAgICAgICAgIHJldHVybjtcbiAgICAgICAgICAgIH1cblxuICAgICAgICAgICAgY29uc3QgZGF0YTogRXhwb3J0UmVzcG9uc2UgPSByZXNwb25zZS5qc29uO1xuICAgICAgICAgICAgYXdhaXQgdGhpcy53cml0ZUhpZ2hsaWdodHMoZGF0YSk7XG5cbiAgICAgICAgICAgIC8vIFVwZGF0ZSBsYXN0IHN5bmMgdGltZXN0YW1wXG4gICAgICAgICAgICB0aGlzLnNldHRpbmdzLmxhc3RTeW5jID0gbmV3IERhdGUoKS50b0lTT1N0cmluZygpO1xuICAgICAgICAgICAgYXdhaXQgdGhpcy5zYXZlU2V0dGluZ3MoKTtcblxuICAgICAgICAgICAgbmV3IE5vdGljZShg4pyFIENvbW1vbnBsYWNlOiBTeW5jZWQgJHtkYXRhLnRvdGFsfSBoaWdobGlnaHRzIGZyb20gJHtkYXRhLnRvdGFsX2Jvb2tzfSBib29rc2ApO1xuICAgICAgICB9IGNhdGNoIChlKSB7XG4gICAgICAgICAgICBuZXcgTm90aWNlKGDimqDvuI8gQ29tbW9ucGxhY2Ugc3luYyBlcnJvcjogJHtlLm1lc3NhZ2UgfHwgZX1gKTtcbiAgICAgICAgfVxuICAgIH1cblxuICAgIGFzeW5jIHdyaXRlSGlnaGxpZ2h0cyhkYXRhOiBFeHBvcnRSZXNwb25zZSkge1xuICAgICAgICAvLyBFbnN1cmUgdGhlIG91dHB1dCBmb2xkZXIgZXhpc3RzXG4gICAgICAgIGNvbnN0IGZvbGRlclBhdGggPSB0aGlzLnNldHRpbmdzLm91dHB1dEZvbGRlciB8fCAnQ29tbW9ucGxhY2UnO1xuICAgICAgICBjb25zdCBmb2xkZXIgPSB0aGlzLmFwcC52YXVsdC5nZXRBYnN0cmFjdEZpbGVCeVBhdGgoZm9sZGVyUGF0aCk7XG4gICAgICAgIGlmICghZm9sZGVyKSB7XG4gICAgICAgICAgICBhd2FpdCB0aGlzLmFwcC52YXVsdC5jcmVhdGVGb2xkZXIoZm9sZGVyUGF0aCk7XG4gICAgICAgIH1cblxuICAgICAgICBmb3IgKGNvbnN0IGJvb2sgb2YgZGF0YS5ib29rcykge1xuICAgICAgICAgICAgY29uc3Qgc2FmZUZpbGVOYW1lID0gdGhpcy5zYW5pdGl6ZUZpbGVOYW1lKGAke2Jvb2sudGl0bGV9Lm1kYCk7XG4gICAgICAgICAgICBjb25zdCBmaWxlUGF0aCA9IGAke2ZvbGRlclBhdGh9LyR7c2FmZUZpbGVOYW1lfWA7XG5cbiAgICAgICAgICAgIC8vIEJ1aWxkIG1hcmtkb3duIGNvbnRlbnQgbWF0Y2hpbmcgUmVhZHdpc2UgZm9ybWF0XG4gICAgICAgICAgICBjb25zdCBjb250ZW50ID0gdGhpcy5idWlsZE1hcmtkb3duKGJvb2spO1xuXG4gICAgICAgICAgICAvLyBXcml0ZSBvciB1cGRhdGUgdGhlIGZpbGVcbiAgICAgICAgICAgIGNvbnN0IGV4aXN0aW5nID0gdGhpcy5hcHAudmF1bHQuZ2V0QWJzdHJhY3RGaWxlQnlQYXRoKGZpbGVQYXRoKTtcbiAgICAgICAgICAgIGlmIChleGlzdGluZykge1xuICAgICAgICAgICAgICAgIGF3YWl0IHRoaXMuYXBwLnZhdWx0Lm1vZGlmeShleGlzdGluZyBhcyBhbnksIGNvbnRlbnQpO1xuICAgICAgICAgICAgfSBlbHNlIHtcbiAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLmFwcC52YXVsdC5jcmVhdGUoZmlsZVBhdGgsIGNvbnRlbnQpO1xuICAgICAgICAgICAgfVxuICAgICAgICB9XG4gICAgfVxuXG4gICAgYnVpbGRNYXJrZG93bihib29rOiBCb29rRGF0YSk6IHN0cmluZyB7XG4gICAgICAgIGNvbnN0IGxpbmVzOiBzdHJpbmdbXSA9IFtdO1xuICAgICAgICBsaW5lcy5wdXNoKGAjICR7Ym9vay50aXRsZX1gKTtcbiAgICAgICAgbGluZXMucHVzaCgnJyk7XG4gICAgICAgIGxpbmVzLnB1c2goJyMjIE1ldGFkYXRhJyk7XG4gICAgICAgIGlmIChib29rLmF1dGhvcikge1xuICAgICAgICAgICAgbGluZXMucHVzaChgLSBBdXRob3I6IFtbJHtib29rLmF1dGhvcn1dXWApO1xuICAgICAgICB9XG4gICAgICAgIGxpbmVzLnB1c2goYC0gRnVsbCBUaXRsZTogJHtib29rLnRpdGxlfWApO1xuICAgICAgICBsaW5lcy5wdXNoKCctIENhdGVnb3J5OiAjYm9va3MnKTtcbiAgICAgICAgbGluZXMucHVzaCgnJyk7XG4gICAgICAgIGxpbmVzLnB1c2goJyMjIEhpZ2hsaWdodHMnKTtcbiAgICAgICAgbGluZXMucHVzaCgnJyk7XG5cbiAgICAgICAgZm9yIChjb25zdCBoIG9mIGJvb2suaGlnaGxpZ2h0cykge1xuICAgICAgICAgICAgY29uc3QgcGFnZVN0ciA9IGgucGFnZSA/IGAgKHAuICR7aC5wYWdlfSlgIDogJyc7XG4gICAgICAgICAgICBsaW5lcy5wdXNoKGAtICR7aC50ZXh0fSR7cGFnZVN0cn1gKTtcbiAgICAgICAgICAgIGlmIChoLnRhZ3MgJiYgaC50YWdzLmxlbmd0aCA+IDApIHtcbiAgICAgICAgICAgICAgICBjb25zdCB0YWdTdHIgPSBoLnRhZ3MubWFwKHQgPT4gYFtbJHt0fV1dYCkuam9pbignICcpO1xuICAgICAgICAgICAgICAgIGxpbmVzLnB1c2goYCAgICAtIFRhZ3M6ICR7dGFnU3RyfWApO1xuICAgICAgICAgICAgfVxuICAgICAgICAgICAgaWYgKGgubm90ZSkge1xuICAgICAgICAgICAgICAgIGxpbmVzLnB1c2goYCAgICAtICoqTm90ZToqKiAke2gubm90ZX1gKTtcbiAgICAgICAgICAgIH1cbiAgICAgICAgICAgIGxpbmVzLnB1c2goJycpO1xuICAgICAgICB9XG5cbiAgICAgICAgcmV0dXJuIGxpbmVzLmpvaW4oJ1xcbicpO1xuICAgIH1cblxuICAgIHNhbml0aXplRmlsZU5hbWUobmFtZTogc3RyaW5nKTogc3RyaW5nIHtcbiAgICAgICAgcmV0dXJuIG5hbWUucmVwbGFjZSgvW1xcXFwvOio/XCI8PnxdL2csICctJykucmVwbGFjZSgvXFxzKy9nLCAnICcpO1xuICAgIH1cbn1cblxuY2xhc3MgQ29tbW9ucGxhY2VTZXR0aW5nVGFiIGV4dGVuZHMgUGx1Z2luU2V0dGluZ1RhYiB7XG4gICAgcGx1Z2luOiBDb21tb25wbGFjZVBsdWdpbjtcblxuICAgIGNvbnN0cnVjdG9yKGFwcDogQXBwLCBwbHVnaW46IENvbW1vbnBsYWNlUGx1Z2luKSB7XG4gICAgICAgIHN1cGVyKGFwcCwgcGx1Z2luKTtcbiAgICAgICAgdGhpcy5wbHVnaW4gPSBwbHVnaW47XG4gICAgfVxuXG4gICAgZGlzcGxheSgpOiB2b2lkIHtcbiAgICAgICAgY29uc3QgeyBjb250YWluZXJFbCB9ID0gdGhpcztcbiAgICAgICAgY29udGFpbmVyRWwuZW1wdHkoKTtcblxuICAgICAgICBjb250YWluZXJFbC5jcmVhdGVFbCgnaDInLCB7IHRleHQ6ICdDb21tb25wbGFjZSBTeW5jIFNldHRpbmdzJyB9KTtcblxuICAgICAgICBuZXcgU2V0dGluZyhjb250YWluZXJFbClcbiAgICAgICAgICAgIC5zZXROYW1lKCdTZXJ2ZXIgVVJMJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdZb3VyIENvbW1vbnBsYWNlIHNlcnZlciBVUkwgKGUuZy4gaHR0cHM6Ly9jb21tb25wbGFjZS55b3VyZG9tYWluLmNvbSknKVxuICAgICAgICAgICAgLmFkZFRleHQodGV4dCA9PiB0ZXh0XG4gICAgICAgICAgICAgICAgLnNldFBsYWNlaG9sZGVyKCdodHRwczovLy4uLicpXG4gICAgICAgICAgICAgICAgLnNldFZhbHVlKHRoaXMucGx1Z2luLnNldHRpbmdzLnNlcnZlclVybClcbiAgICAgICAgICAgICAgICAub25DaGFuZ2UoYXN5bmMgKHZhbHVlKSA9PiB7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMucGx1Z2luLnNldHRpbmdzLnNlcnZlclVybCA9IHZhbHVlO1xuICAgICAgICAgICAgICAgICAgICBhd2FpdCB0aGlzLnBsdWdpbi5zYXZlU2V0dGluZ3MoKTtcbiAgICAgICAgICAgICAgICB9KSk7XG5cbiAgICAgICAgbmV3IFNldHRpbmcoY29udGFpbmVyRWwpXG4gICAgICAgICAgICAuc2V0TmFtZSgnQVBJIFRva2VuJylcbiAgICAgICAgICAgIC5zZXREZXNjKCdBUEkgdG9rZW4gZnJvbSBDb21tb25wbGFjZSBTZXR0aW5ncyBwYWdlJylcbiAgICAgICAgICAgIC5hZGRUZXh0KHRleHQgPT4gdGV4dFxuICAgICAgICAgICAgICAgIC5zZXRQbGFjZWhvbGRlcigneW91ci10b2tlbicpXG4gICAgICAgICAgICAgICAgLnNldFZhbHVlKHRoaXMucGx1Z2luLnNldHRpbmdzLmFwaVRva2VuKVxuICAgICAgICAgICAgICAgIC5vbkNoYW5nZShhc3luYyAodmFsdWUpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dGluZ3MuYXBpVG9rZW4gPSB2YWx1ZTtcbiAgICAgICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5wbHVnaW4uc2F2ZVNldHRpbmdzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ091dHB1dCBGb2xkZXInKVxuICAgICAgICAgICAgLnNldERlc2MoJ0ZvbGRlciBpbiB5b3VyIHZhdWx0IHdoZXJlIGhpZ2hsaWdodCBub3RlcyB3aWxsIGJlIHNhdmVkJylcbiAgICAgICAgICAgIC5hZGRUZXh0KHRleHQgPT4gdGV4dFxuICAgICAgICAgICAgICAgIC5zZXRQbGFjZWhvbGRlcignQ29tbW9ucGxhY2UnKVxuICAgICAgICAgICAgICAgIC5zZXRWYWx1ZSh0aGlzLnBsdWdpbi5zZXR0aW5ncy5vdXRwdXRGb2xkZXIpXG4gICAgICAgICAgICAgICAgLm9uQ2hhbmdlKGFzeW5jICh2YWx1ZSkgPT4ge1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zZXR0aW5ncy5vdXRwdXRGb2xkZXIgPSB2YWx1ZTtcbiAgICAgICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5wbHVnaW4uc2F2ZVNldHRpbmdzKCk7XG4gICAgICAgICAgICAgICAgfSkpO1xuXG4gICAgICAgIG5ldyBTZXR0aW5nKGNvbnRhaW5lckVsKVxuICAgICAgICAgICAgLnNldE5hbWUoJ0xhc3QgU3luYycpXG4gICAgICAgICAgICAuc2V0RGVzYyh0aGlzLnBsdWdpbi5zZXR0aW5ncy5sYXN0U3luY1xuICAgICAgICAgICAgICAgID8gYExhc3Qgc3luY2VkOiAke3RoaXMucGx1Z2luLnNldHRpbmdzLmxhc3RTeW5jfWBcbiAgICAgICAgICAgICAgICA6ICdObyBzeW5jIHlldCcpXG4gICAgICAgICAgICAuYWRkQnV0dG9uKGJ0biA9PiBidG5cbiAgICAgICAgICAgICAgICAuc2V0QnV0dG9uVGV4dCgnU3luYyBOb3cnKVxuICAgICAgICAgICAgICAgIC5vbkNsaWNrKCgpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc3luY0hpZ2hsaWdodHMoKTtcbiAgICAgICAgICAgICAgICB9KSk7XG5cbiAgICAgICAgY29udGFpbmVyRWwuY3JlYXRlRWwoJ2hyJyk7XG5cbiAgICAgICAgbmV3IFNldHRpbmcoY29udGFpbmVyRWwpXG4gICAgICAgICAgICAuc2V0TmFtZSgnU3luYyBBbGwnKVxuICAgICAgICAgICAgLnNldERlc2MoJ0NsZWFyIHRoZSBsYXN0IHN5bmMgdGltZXN0YW1wIGFuZCBwdWxsIGV2ZXJ5dGhpbmcgYWdhaW4nKVxuICAgICAgICAgICAgLmFkZEJ1dHRvbihidG4gPT4gYnRuXG4gICAgICAgICAgICAgICAgLnNldEJ1dHRvblRleHQoJ1Jlc2V0IGFuZCBTeW5jIEFsbCcpXG4gICAgICAgICAgICAgICAgLnNldFdhcm5pbmcoKVxuICAgICAgICAgICAgICAgIC5vbkNsaWNrKGFzeW5jICgpID0+IHtcbiAgICAgICAgICAgICAgICAgICAgdGhpcy5wbHVnaW4uc2V0dGluZ3MubGFzdFN5bmMgPSAnJztcbiAgICAgICAgICAgICAgICAgICAgYXdhaXQgdGhpcy5wbHVnaW4uc2F2ZVNldHRpbmdzKCk7XG4gICAgICAgICAgICAgICAgICAgIHRoaXMuZGlzcGxheSgpO1xuICAgICAgICAgICAgICAgICAgICB0aGlzLnBsdWdpbi5zeW5jSGlnaGxpZ2h0cygpO1xuICAgICAgICAgICAgICAgIH0pKTtcbiAgICB9XG59XG4iXX0=