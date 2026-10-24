import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PaginationComponent, buildPageList } from './pagination.component';

describe('buildPageList', () => {
  it('returns an empty list when there are no pages', () => {
    expect(buildPageList(0, 1)).toEqual([]);
  });

  it('lists every page when the total is small', () => {
    expect(buildPageList(5, 3)).toEqual([1, 2, 3, 4, 5]);
    expect(buildPageList(7, 1)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it('collapses the tail when near the start', () => {
    expect(buildPageList(10, 1)).toEqual([1, 2, 'ellipsis', 10]);
  });

  it('collapses both sides around the current page', () => {
    expect(buildPageList(10, 5)).toEqual([
      1,
      'ellipsis',
      4,
      5,
      6,
      'ellipsis',
      10,
    ]);
  });

  it('collapses the head when near the end', () => {
    expect(buildPageList(10, 10)).toEqual([1, 'ellipsis', 9, 10]);
  });

  it('never returns more than seven items for large totals', () => {
    for (let current = 1; current <= 50; current++) {
      expect(buildPageList(50, current).length).toBeLessThanOrEqual(7);
    }
  });

  it('always includes the first page, last page, and the current page', () => {
    const pages = buildPageList(50, 25);
    expect(pages[0]).toBe(1);
    expect(pages[pages.length - 1]).toBe(50);
    expect(pages).toContain(25);
  });
});

describe('PaginationComponent', () => {
  let fixture: ComponentFixture<PaginationComponent>;
  let component: PaginationComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PaginationComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(PaginationComponent);
    component = fixture.componentInstance;
  });

  function render(values: {
    currentPage?: number;
    totalPages?: number;
    totalItems?: number;
    pageSize?: number;
    showPageSize?: boolean;
  }): void {
    fixture.componentRef.setInput('currentPage', values.currentPage ?? 1);
    fixture.componentRef.setInput('totalPages', values.totalPages ?? 1);
    fixture.componentRef.setInput('totalItems', values.totalItems ?? 0);
    fixture.componentRef.setInput('pageSize', values.pageSize ?? 0);
    fixture.componentRef.setInput(
      'showPageSize',
      values.showPageSize ?? false,
    );
    fixture.detectChanges();
  }

  function byLabel(label: string): HTMLButtonElement {
    return fixture.nativeElement.querySelector(
      `[aria-label="${label}"]`,
    ) as HTMLButtonElement;
  }

  it('renders the item range and marks the active page', () => {
    render({ currentPage: 3, totalPages: 10, totalItems: 120, pageSize: 12 });

    const range = fixture.nativeElement.querySelector('.pg-range');
    expect(range.textContent.replace(/\s+/g, ' ').trim()).toBe(
      'Showing 25–36 of 120',
    );
    const active = fixture.nativeElement.querySelector('[aria-current="page"]');
    expect(active.textContent.trim()).toBe('3');
    expect(byLabel('Previous page').disabled).toBeFalse();
    expect(byLabel('Next page').disabled).toBeFalse();
  });

  it('emits the next and previous page', () => {
    render({ currentPage: 3, totalPages: 10 });
    const emitted: number[] = [];
    component.pageChange.subscribe((page) => emitted.push(page));

    byLabel('Next page').click();
    byLabel('Previous page').click();

    expect(emitted).toEqual([4, 2]);
  });

  it('does not emit when the active page is clicked', () => {
    render({ currentPage: 3, totalPages: 10 });
    const emitted: number[] = [];
    component.pageChange.subscribe((page) => emitted.push(page));

    (fixture.nativeElement.querySelector('.pg-num--active') as HTMLElement).click();

    expect(emitted).toEqual([]);
  });

  it('disables all navigation on a single page', () => {
    render({ currentPage: 1, totalPages: 1, totalItems: 5, pageSize: 12 });

    expect(byLabel('First page').disabled).toBeTrue();
    expect(byLabel('Previous page').disabled).toBeTrue();
    expect(byLabel('Next page').disabled).toBeTrue();
    expect(byLabel('Last page').disabled).toBeTrue();
  });

  it('emits a new page size and reflects the current selection', () => {
    render({
      currentPage: 1,
      totalPages: 2,
      totalItems: 20,
      pageSize: 12,
      showPageSize: true,
    });
    const select = fixture.nativeElement.querySelector(
      '.pg-size__select',
    ) as HTMLSelectElement;
    expect(select.value).toBe('12');
    const emitted: number[] = [];
    component.pageSizeChange.subscribe((size) => emitted.push(size));

    select.value = '24';
    select.dispatchEvent(new Event('change'));

    expect(emitted).toEqual([24]);
  });
});
