import { Component, computed, input, output } from '@angular/core';

export type PageItem = number | 'ellipsis';

/**
 * Build a windowed page list: always shows the first and last page plus the
 * current page and its neighbours, collapsing the gaps with an ellipsis.
 *
 * Examples (siblingCount = 1):
 *   (5, 1)  -> [1, 2, 3, 4, 5]
 *   (10, 1) -> [1, 2, 'ellipsis', 10]
 *   (10, 5) -> [1, 'ellipsis', 4, 5, 6, 'ellipsis', 10]
 *   (10, 10) -> [1, 'ellipsis', 9, 10]
 */
export function buildPageList(
  total: number,
  current: number,
  siblingCount = 1,
): PageItem[] {
  if (total <= 0) {
    return [];
  }
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const left = Math.max(2, current - siblingCount);
  const right = Math.min(total - 1, current + siblingCount);

  const pages: PageItem[] = [1];
  if (left > 2) {
    pages.push('ellipsis');
  }
  for (let page = left; page <= right; page++) {
    pages.push(page);
  }
  if (right < total - 1) {
    pages.push('ellipsis');
  }
  pages.push(total);
  return pages;
}

@Component({
  selector: 'app-pagination',
  templateUrl: './pagination.component.html',
  styleUrl: './pagination.component.css',
})
export class PaginationComponent {
  readonly currentPage = input.required<number>();
  readonly totalPages = input.required<number>();
  readonly totalItems = input(0);
  readonly pageSize = input(0);
  readonly showPageSize = input(false);
  readonly pageSizeOptions = input<readonly number[]>([12, 24, 48]);

  readonly pageChange = output<number>();
  readonly pageSizeChange = output<number>();

  protected readonly pages = computed<PageItem[]>(() =>
    buildPageList(this.totalPages(), this.currentPage()),
  );

  protected readonly firstItem = computed(() => {
    const size = this.pageSize();
    if (this.totalItems() <= 0 || size <= 0) {
      return 0;
    }
    return (this.currentPage() - 1) * size + 1;
  });

  protected readonly lastItem = computed(() => {
    const size = this.pageSize();
    if (size <= 0) {
      return 0;
    }
    return Math.min(this.currentPage() * size, this.totalItems());
  });

  protected go(page: number): void {
    const clamped = Math.min(Math.max(page, 1), this.totalPages());
    if (clamped !== this.currentPage()) {
      this.pageChange.emit(clamped);
    }
  }

  protected onPageSizeChange(event: Event): void {
    const value = Number((event.target as HTMLSelectElement).value);
    if (value > 0 && value !== this.pageSize()) {
      this.pageSizeChange.emit(value);
    }
  }
}
