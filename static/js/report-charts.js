/**
 * Blik Report Charts
 * Mobile-first chart rendering with theme support
 */

(function() {
    'use strict';

    // Get theme-aware colors
    function getThemeColors() {
        const style = getComputedStyle(document.documentElement);
        return {
            primary: style.getPropertyValue('--primary').trim() || '#4f46e5',
            self: style.getPropertyValue('--primary').trim() || '#4f46e5',
            peer: style.getPropertyValue('--success').trim() || '#10b981',
            manager: style.getPropertyValue('--warning').trim() || '#f59e0b',
            direct_report: style.getPropertyValue('--insight-skill').trim() || '#3b82f6',
            others: style.getPropertyValue('--secondary').trim() || '#64748b',
            text: style.getPropertyValue('--text-primary').trim() || '#1e293b',
            textSecondary: style.getPropertyValue('--text-secondary').trim() || '#64748b',
            border: style.getPropertyValue('--border').trim() || '#e2e8f0',
            bgCard: style.getPropertyValue('--bg-card').trim() || '#ffffff'
        };
    }

    // Check if mobile
    function isMobile() {
        return window.innerWidth < 768;
    }

    // Category display names
    const categoryLabels = {
        'self': 'Self',
        'peer': 'Peers',
        'manager': 'Manager',
        'direct_report': 'Direct Reports',
        'others_avg': 'Others Average'
    };

    /**
     * Render section radar chart
     * Shows section averages with self vs others overlay
     */
    window.renderSectionRadarChart = function(canvasId, chartData) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const colors = getThemeColors();
        const sections = chartData.section_scores || {};
        const sectionNames = Object.keys(sections);

        if (sectionNames.length === 0) {
            ctx.parentElement.innerHTML = '<p style="text-align: center; color: var(--text-secondary);">No chart data available</p>';
            return;
        }

        // Prepare datasets
        const datasets = [];
        const categories = ['self', 'peer', 'manager', 'direct_report'];

        categories.forEach(category => {
            const data = sectionNames.map(section =>
                sections[section][category] || null
            );

            // Only add if there's data
            if (data.some(v => v !== null)) {
                datasets.push({
                    label: categoryLabels[category],
                    data: data,
                    borderColor: colors[category],
                    backgroundColor: colors[category] + '20',
                    borderWidth: 2,
                    pointRadius: 4,
                    pointBackgroundColor: colors[category],
                    pointBorderColor: colors.bgCard,
                    pointBorderWidth: 2
                });
            }
        });

        // On mobile, use horizontal bar chart instead
        if (isMobile()) {
            renderMobileSectionChart(canvasId, sectionNames, sections, colors);
            return;
        }

        // Radar chart configuration
        new Chart(ctx, {
            type: 'radar',
            data: {
                labels: sectionNames,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 1.5,
                scales: {
                    r: {
                        min: 1,
                        max: 5,
                        ticks: {
                            stepSize: 1,
                            color: colors.textSecondary,
                            backdropColor: 'transparent'
                        },
                        grid: {
                            color: colors.border
                        },
                        pointLabels: {
                            color: colors.text,
                            font: {
                                size: 12,
                                weight: '500'
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            padding: 15,
                            font: {
                                size: 13
                            },
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        backgroundColor: colors.bgCard,
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.border,
                        borderWidth: 1,
                        padding: 12,
                        displayColors: true,
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': ' + context.parsed.r.toFixed(1);
                            }
                        }
                    }
                }
            }
        });
    };

    /**
     * Render mobile-friendly stacked bar chart for sections
     */
    function renderMobileSectionChart(canvasId, sectionNames, sections, colors) {
        const ctx = document.getElementById(canvasId);
        const categories = ['self', 'peer', 'manager', 'direct_report'];

        const datasets = categories.map(category => ({
            label: categoryLabels[category],
            data: sectionNames.map(section => sections[section][category] || 0),
            backgroundColor: colors[category],
            borderWidth: 0
        })).filter(ds => ds.data.some(v => v > 0));

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: sectionNames,
                datasets: datasets
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        min: 1,
                        max: 5,
                        ticks: {
                            color: colors.textSecondary
                        },
                        grid: {
                            color: colors.border
                        }
                    },
                    y: {
                        ticks: {
                            color: colors.text,
                            font: {
                                size: 11
                            }
                        },
                        grid: {
                            display: false
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            padding: 10,
                            font: {
                                size: 11
                            },
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        backgroundColor: colors.bgCard,
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.border,
                        borderWidth: 1,
                        padding: 10
                    }
                }
            }
        });
    }

    /**
     * Render self vs others gap chart
     */
    window.renderGapChart = function(canvasId, chartData) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const colors = getThemeColors();
        const sections = chartData.section_scores || {};
        const sectionNames = Object.keys(sections);

        if (sectionNames.length === 0) return;

        // Calculate gaps and sort by size
        const gaps = sectionNames.map(section => {
            const self = sections[section].self || 0;
            const others = sections[section].others_avg || 0;
            return {
                section: section,
                self: self,
                others: others,
                gap: self - others
            };
        }).sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: gaps.map(g => g.section),
                datasets: [
                    {
                        label: 'Self',
                        data: gaps.map(g => g.self),
                        backgroundColor: colors.self + 'cc',
                        borderWidth: 0
                    },
                    {
                        label: 'Others Average',
                        data: gaps.map(g => g.others),
                        backgroundColor: colors.others + 'cc',
                        borderWidth: 0
                    }
                ]
            },
            options: {
                indexAxis: isMobile() ? 'y' : 'x',
                responsive: true,
                maintainAspectRatio: !isMobile(),
                aspectRatio: isMobile() ? undefined : 2,
                scales: {
                    x: isMobile() ? {
                        min: 1,
                        max: 5,
                        ticks: { color: colors.textSecondary },
                        grid: { color: colors.border }
                    } : {
                        ticks: { color: colors.text },
                        grid: { display: false }
                    },
                    y: isMobile() ? {
                        ticks: { color: colors.text, font: { size: 11 } },
                        grid: { display: false }
                    } : {
                        min: 1,
                        max: 5,
                        ticks: { color: colors.textSecondary },
                        grid: { color: colors.border }
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: colors.text,
                            padding: 15,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        backgroundColor: colors.bgCard,
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.border,
                        borderWidth: 1,
                        padding: 12,
                        callbacks: {
                            afterBody: function(context) {
                                if (context.length === 2) {
                                    const gap = context[0].parsed.y - context[1].parsed.y;
                                    return '\nGap: ' + (gap > 0 ? '+' : '') + gap.toFixed(2);
                                }
                            }
                        }
                    }
                }
            }
        });
    };

    /**
     * Render category breakdown chart for a section
     */
    window.renderCategoryBreakdownChart = function(canvasId, sectionName, sectionData) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        const colors = getThemeColors();
        const categories = ['self', 'peer', 'manager', 'direct_report'];

        const data = categories.map(cat => sectionData[cat] || 0)
            .filter(v => v > 0);
        const labels = categories
            .filter(cat => sectionData[cat] > 0)
            .map(cat => categoryLabels[cat]);

        if (data.length === 0) return;

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: sectionName,
                    data: data,
                    backgroundColor: categories
                        .filter(cat => sectionData[cat] > 0)
                        .map(cat => colors[cat]),
                    borderWidth: 0,
                    borderRadius: 6
                }]
            },
            options: {
                indexAxis: isMobile() ? 'y' : 'x',
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: isMobile() ? 1.5 : 2,
                scales: {
                    x: isMobile() ? {
                        min: 1,
                        max: 5,
                        ticks: { color: colors.textSecondary },
                        grid: { color: colors.border }
                    } : {
                        ticks: { color: colors.text },
                        grid: { display: false }
                    },
                    y: isMobile() ? {
                        ticks: { color: colors.text },
                        grid: { display: false }
                    } : {
                        min: 1,
                        max: 5,
                        ticks: { color: colors.textSecondary },
                        grid: { color: colors.border }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: colors.bgCard,
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.border,
                        borderWidth: 1,
                        padding: 10
                    }
                }
            }
        });
    };

    // Re-render charts on theme change
    function observeThemeChanges() {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.attributeName === 'data-theme') {
                    // Charts need to be manually destroyed and recreated
                    // This is handled by page reload or explicit re-render
                    window.location.reload();
                }
            });
        });

        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme']
        });
    }

    // Initialize on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observeThemeChanges);
    } else {
        observeThemeChanges();
    }

})();
