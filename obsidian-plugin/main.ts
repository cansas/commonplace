import { App, Plugin, PluginSettingTab, Setting, Notice, requestUrl } from 'obsidian';

interface CommonplaceSettings {
    serverUrl: string;
    apiToken: string;
    outputFolder: string;
    lastSync: string;
    autoSync: boolean;
    syncInterval: number;
}

const DEFAULT_SETTINGS: CommonplaceSettings = {
    serverUrl: '',
    apiToken: '',
    outputFolder: 'Commonplace',
    lastSync: '',
    autoSync: true,
    syncInterval: 6,
};

interface HighlightData {
    id: number;
    text: string;
    note: string | null;
    page: number | null;
    chapter: string | null;
    color: string | null;
    favorite: boolean;
    highlighted_at: string | null;
    created_at: string | null;
    tags: string[];
}

interface BookData {
    title: string;
    author: string;
    highlights: HighlightData[];
}

interface ExportResponse {
    books: BookData[];
    total: number;
    total_books: number;
}

export default class CommonplacePlugin extends Plugin {
    settings: CommonplaceSettings;
    _intervalHandle: number | null = null;

    async onload() {
        await this.loadSettings();

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

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    async syncHighlights() {
        // Validate settings
        if (!this.settings.serverUrl || !this.settings.apiToken) {
            new Notice('⚠️ Commonplace: Configure server URL and API token in Settings first');
            return;
        }

        new Notice('🔄 Syncing from Commonplace...');
        const serverUrl = this.settings.serverUrl.replace(/\/+$/, '');
        const since = this.settings.lastSync || '';

        try {
            const url = `${serverUrl}/api/export${since ? '?since=' + encodeURIComponent(since) : ''}`;
            const response = await requestUrl({
                url: url,
                method: 'GET',
                headers: {
                    'Authorization': `Token ${this.settings.apiToken}`,
                },
            });

            if (response.status !== 200) {
                new Notice(`⚠️ Commonplace sync failed: HTTP ${response.status}`);
                return;
            }

            const data: ExportResponse = response.json;
            await this.writeHighlights(data);

            // Update last sync timestamp
            this.settings.lastSync = new Date().toISOString();
            await this.saveSettings();

            new Notice(`✅ Commonplace: Synced ${data.total} highlights from ${data.total_books} books`);
        } catch (e) {
            new Notice(`⚠️ Commonplace sync error: ${e.message || e}`);
        }
    }

    async writeHighlights(data: ExportResponse) {
        // Ensure the output folder exists
        const folderPath = this.settings.outputFolder || 'Commonplace';
        const folder = this.app.vault.getAbstractFileByPath(folderPath);
        if (!folder) {
            await this.app.vault.createFolder(folderPath);
        }

        for (const book of data.books) {
            const safeFileName = this.sanitizeFileName(`${book.title}.md`);
            const filePath = `${folderPath}/${safeFileName}`;

            // Build markdown content matching Readwise format
            const content = this.buildMarkdown(book);

            // Write or update the file
            const existing = this.app.vault.getAbstractFileByPath(filePath);
            if (existing) {
                await this.app.vault.modify(existing as any, content);
            } else {
                await this.app.vault.create(filePath, content);
            }
        }
    }

    buildMarkdown(book: BookData): string {
        const lines: string[] = [];
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

    sanitizeFileName(name: string): string {
        return name.replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, ' ');
    }
}

class CommonplaceSettingTab extends PluginSettingTab {
    plugin: CommonplacePlugin;

    constructor(app: App, plugin: CommonplacePlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        containerEl.createEl('h2', { text: 'Commonplace Sync Settings' });

        new Setting(containerEl)
            .setName('Server URL')
            .setDesc('Your Commonplace server URL (e.g. https://commonplace.yourdomain.com)')
            .addText(text => text
                .setPlaceholder('https://...')
                .setValue(this.plugin.settings.serverUrl)
                .onChange(async (value) => {
                    this.plugin.settings.serverUrl = value;
                    await this.plugin.saveSettings();
                    this.plugin.setupInterval();
                }));

        new Setting(containerEl)
            .setName('API Token')
            .setDesc('API token from Commonplace Settings page')
            .addText(text => text
                .setPlaceholder('your-token')
                .setValue(this.plugin.settings.apiToken)
                .onChange(async (value) => {
                    this.plugin.settings.apiToken = value;
                    await this.plugin.saveSettings();
                    this.plugin.setupInterval();
                }));

        new Setting(containerEl)
            .setName('Output Folder')
            .setDesc('Folder in your vault where highlight notes will be saved')
            .addText(text => text
                .setPlaceholder('Commonplace')
                .setValue(this.plugin.settings.outputFolder)
                .onChange(async (value) => {
                    this.plugin.settings.outputFolder = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Auto-sync on startup')
            .setDesc('Automatically sync highlights when Obsidian opens')
            .addToggle(toggle => toggle
                .setValue(this.plugin.settings.autoSync)
                .onChange(async (value) => {
                    this.plugin.settings.autoSync = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Sync interval')
            .setDesc('How often to auto-sync while Obsidian is open (hours, 0 = off)')
            .addSlider(slider => slider
                .setLimits(0, 24, 1)
                .setValue(this.plugin.settings.syncInterval)
                .setDynamicTooltip()
                .onChange(async (value) => {
                    this.plugin.settings.syncInterval = value;
                    await this.plugin.saveSettings();
                    this.plugin.setupInterval();
                }));

        new Setting(containerEl)
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

        new Setting(containerEl)
            .setName('Sync All')
            .setDesc('Clear the last sync timestamp and pull everything again')
            .addButton(btn => btn
                .setButtonText('Reset and Sync All')
                .setWarning()
                .onClick(async () => {
                    this.plugin.settings.lastSync = '';
                    await this.plugin.saveSettings();
                    this.display();
                    this.plugin.syncHighlights();
                }));
    }
}
