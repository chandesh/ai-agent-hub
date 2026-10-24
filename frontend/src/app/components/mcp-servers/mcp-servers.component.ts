import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { ApiService } from '../../services/api.service';
import { FavoritesService } from '../../services/favorites.service';
import { MCPServer, Category } from '../../models/agent.model';
import { HeaderComponent } from '../header/header.component';
import { FooterComponent } from '../footer/footer.component';
import { FavoriteButtonComponent } from '../favorite-button/favorite-button.component';
import { LoginWallComponent } from '../login-wall/login-wall.component';
import { PaginationComponent } from '../pagination/pagination.component';

@Component({
  selector: 'app-mcp-servers',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, HeaderComponent, FooterComponent, FavoriteButtonComponent, LoginWallComponent, PaginationComponent],
  templateUrl: './mcp-servers.component.html',
  styleUrls: ['./mcp-servers.component.css']
})
export class McpServersComponent implements OnInit {
  servers: MCPServer[] = [];
  categories: Category[] = [];
  languages: string[] = [];
  loading = false;
  error: string | null = null;
  isGuestPreview = false;
  
  // Pagination
  currentPage = 1;
  totalPages = 1;
  totalServers = 0;
  limit = 12;
  
  // Filters
  searchQuery = '';
  selectedCategory = '';
  selectedLanguage = '';
  selectedScope = '';
  showFeaturedOnly = false;
  selectedDatePreset = '';
  customDateFrom = '';
  customDateTo = '';
  
  // Sorting
  selectedSort = 'star_count_desc';

  constructor(
    private apiService: ApiService,
    private favoritesService: FavoritesService,
    private router: Router,
    private route: ActivatedRoute,
    private destroyRef: DestroyRef
  ) {}

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    this.currentPage = this.parsePage(params.get('page'));
    this.limit = this.parseLimit(params.get('limit'));

    this.loadCategories();
    this.loadLanguages();
    this.loadServers();
    this.favoritesService.refreshFavoritesState();

    this.route.queryParamMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((query) => {
        const page = this.parsePage(query.get('page'));
        const limit = this.parseLimit(query.get('limit'));
        if (page !== this.currentPage || limit !== this.limit) {
          this.currentPage = page;
          this.limit = limit;
          this.loadServers();
        }
      });
  }

  loadCategories(): void {
    this.apiService.getCategories().subscribe({
      next: (response) => {
        if (response.success && response.data) {
          this.categories = response.data.categories;
        }
      },
      error: (error) => {
        console.error('Error loading categories:', error);
      }
    });
  }

  loadLanguages(): void {
    this.apiService.getLanguages().subscribe({
      next: (response) => {
        if (response.success && response.data) {
          this.languages = response.data.languages;
        }
      },
      error: (error) => {
        console.error('Error loading languages:', error);
      }
    });
  }

  loadServers(): void {
    this.loading = true;
    this.error = null;
    const dateRange = this.resolveDateRange();

    // Parse sort selection
    const parts = this.selectedSort.split('_');
    let sortBy, sortOrder;
    
    if (parts.length === 3) {
      // Handle cases like 'star_count_desc' or 'view_count_desc'
      sortBy = `${parts[0]}_${parts[1]}`;
      sortOrder = parts[2];
    } else {
      // Handle cases like 'name_desc' or 'name_asc'
      sortBy = parts[0];
      sortOrder = parts[1];
    }

    if (this.searchQuery.trim()) {
      // Search mode
      this.apiService.searchMCPServers(this.searchQuery, this.currentPage, this.limit, sortBy, sortOrder, dateRange.date_from, dateRange.date_to).subscribe({
        next: (response) => {
          this.handleServersResponse(response);
        },
        error: (error) => {
          this.handleError(error);
        }
      });
    } else {
      // Regular listing with filters
      const filters: any = {};
      if (this.selectedCategory) filters.category_id = this.selectedCategory;
      if (this.selectedLanguage) filters.language = this.selectedLanguage;
      if (this.selectedScope) filters.scope = this.selectedScope;
      if (this.showFeaturedOnly) filters.featured = true;
      if (dateRange.date_from) filters.date_from = dateRange.date_from;
      if (dateRange.date_to) filters.date_to = dateRange.date_to;
      filters.sort_by = sortBy;
      filters.sort_order = sortOrder;

      this.apiService.getMCPServers(this.currentPage, this.limit, filters).subscribe({
        next: (response) => {
          this.handleServersResponse(response);
        },
        error: (error) => {
          this.handleError(error);
        }
      });
    }
  }

  handleServersResponse(response: any): void {
    this.loading = false;
    if (response.success && response.data) {
      this.servers = response.data.servers;
      this.totalServers = response.data.total;
      this.totalPages = Math.ceil(this.totalServers / this.limit);
      this.isGuestPreview = !!response.data?.is_guest_preview;
      if (this.totalPages > 0 && this.currentPage > this.totalPages) {
        this.currentPage = this.totalPages;
        this.syncUrl(true);
        this.loadServers();
      }
    }
  }

  handleError(error: any): void {
    this.loading = false;
    this.error = 'Failed to load MCP servers. Please try again.';
    console.error('Error loading servers:', error);
  }

  onSearch(): void {
    this.currentPage = 1;
    this.syncUrl();
    this.loadServers();
  }

  onFilterChange(): void {
    this.currentPage = 1;
    this.syncUrl();
    this.loadServers();
  }

  onPageChange(page: number): void {
    this.currentPage = page;
    this.syncUrl();
    this.loadServers();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onPageSizeChange(size: number): void {
    this.limit = size;
    this.currentPage = 1;
    this.syncUrl();
    this.loadServers();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  clearFilters(): void {
    this.searchQuery = '';
    this.selectedCategory = '';
    this.selectedLanguage = '';
    this.selectedScope = '';
    this.showFeaturedOnly = false;
    this.selectedDatePreset = '';
    this.customDateFrom = '';
    this.customDateTo = '';
    this.selectedSort = 'star_count_desc';
    this.currentPage = 1;
    this.syncUrl();
    this.loadServers();
  }

  /** Compute date_from/date_to from the preset or custom inputs. */
  resolveDateRange(): { date_from?: string; date_to?: string } {
    if (this.selectedDatePreset === 'custom') {
      if (!this.customDateFrom || !this.customDateTo) {
        return {};
      }
      return { date_from: this.customDateFrom, date_to: this.customDateTo };
    }
    if (!this.selectedDatePreset) {
      return {};
    }
    const days = parseInt(this.selectedDatePreset, 10);
    const from = new Date();
    from.setDate(from.getDate() - days);
    return { date_from: from.toISOString().slice(0, 10) };
  }

  getDateFilterLabel(): string {
    if (this.selectedDatePreset === 'custom') {
      return `Custom (${this.customDateFrom || '?'} → ${this.customDateTo || '?'})`;
    }
    return `Last ${this.selectedDatePreset} days`;
  }

  getScopeBadgeClass(scope: string): string {
    switch (scope) {
      case 'local': return 'scope-local';
      case 'cloud': return 'scope-cloud';
      case 'hybrid': return 'scope-hybrid';
      default: return 'scope-default';
    }
  }

  getCategoryName(categoryId: string): string {
    const category = this.categories.find(c => c.id === categoryId);
    return category ? category.name : '';
  }

  formatStars(stars: number): string {
    if (stars >= 1000) {
      return `${(stars / 1000).toFixed(1)}k`;
    }
    return stars.toString();
  }

  /** Keep page-size control reachable when a larger size leaves a single page. */
  get showPagination(): boolean {
    return (
      this.totalPages > 1 ||
      (this.limit !== this.defaultLimit && this.totalPages > 0)
    );
  }

  private readonly defaultLimit = 12;
  private readonly allowedLimits = [12, 24, 48];

  private parsePage(value: string | null): number {
    const page = Number(value);
    return Number.isFinite(page) && page >= 1 ? Math.floor(page) : 1;
  }

  private parseLimit(value: string | null): number {
    const limit = Number(value);
    return this.allowedLimits.includes(limit) ? limit : this.defaultLimit;
  }

  /** Keep the current page/size in the URL so refresh and back/forward work. */
  private syncUrl(replaceUrl = false): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        page: this.currentPage > 1 ? this.currentPage : null,
        limit: this.limit !== this.defaultLimit ? this.limit : null,
      },
      queryParamsHandling: 'merge',
      replaceUrl,
    });
  }
}
