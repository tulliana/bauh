import logging
import traceback
from threading import Thread
from typing import Dict, List, Set

from bauh.gems.arch import pacman
from bauh.gems.arch.aur import AURClient
from bauh.gems.arch.model import ArchPackage


class UpdatesSorter:

    def __init__(self, aur_client: AURClient, logger: logging.Logger):
        self.aur_client = aur_client
        self.logger = logger

    @classmethod
    def _add_to_sort(cls, pkg: ArchPackage, pkg_deps: Dict[ArchPackage, Set[str]],  sorted_names: Dict[str, int], not_sorted: Dict[str, ArchPackage], names_map: Dict[str, ArchPackage]) -> int:
        idx = sorted_names.get(pkg.name)

        if idx is not None:
            return idx
        else:
            idx = len(sorted_names)
            sorted_names[pkg.name] = idx

            for dep in pkg_deps[pkg]:
                dep_idx = sorted_names.get(dep)

                if dep_idx is not None:
                    idx = dep_idx + 1
                else:
                    dep_pkg = names_map.get(dep)

                    if dep_pkg:  # it means the declared dep is mapped differently from the provided packages to update
                        dep_idx = sorted_names.get(dep_pkg.name)

                        if dep_idx is not None:
                            idx = dep_idx + 1
                        else:
                            dep_idx = cls._add_to_sort(dep_pkg, pkg_deps, sorted_names, not_sorted, names_map)
                            idx = dep_idx + 1

                    elif dep in not_sorted:  # it means the dep is one of the packages to sort, but it not sorted yet
                        dep_idx = cls._add_to_sort(not_sorted[dep], pkg_deps, sorted_names, not_sorted, names_map)
                        idx = dep_idx + 1

                sorted_names[pkg.name] = idx

            return sorted_names[pkg.name]

    @classmethod
    def _sort_deps(cls, pkg_deps: Dict[ArchPackage, Set[str]], names_map: Dict[str, ArchPackage]) -> List[ArchPackage]:
        sorted_names, not_sorted = {}, {}
        pkg_map = {}

        # first adding all with no deps:
        for pkg, deps in pkg_deps.items():
            if not deps:
                sorted_names[pkg.name] = len(sorted_names)
            else:
                not_sorted[pkg.name] = pkg

            pkg_map[pkg.name] = pkg

        # now adding all that depends on another:
        for name, pkg in not_sorted.items():
            cls._add_to_sort(pkg, pkg_deps, sorted_names, not_sorted, names_map)

        position_map = {'{}-{}'.format(i, n): pkg_map[n] for n, i in sorted_names.items()}
        return [position_map[idx] for idx in sorted(position_map)]

    def _fill_repo_pkgs_sort_data(self, pkgs: List[ArchPackage], pkg_deps: Dict[ArchPackage, Set[str]], names_map: Dict[str, ArchPackage]):
        sorting_data = pacman.map_sorting_data([p.name for p in pkgs])

        for p in pkgs:
            data = sorting_data.get(p)

            if data:
                for name in data['provides']:
                    names_map[name] = p

                pkg_deps[p] = data['depends']
            else:
                names_map[p.name] = p
                pkg_deps[p] = None
                self.logger.warning("Could not retrieve the sorting data for package '{}'".format(p))

    def sort(self, pkgs: Dict[str, ArchPackage]) -> List[ArchPackage]:
        aur_pkgs, repo_pkgs = [], []

        for n, p in pkgs.items():
            if p.repository == 'aur':
                aur_pkgs.append(p)
            else:
                repo_pkgs.append(p)

        pkg_deps = {}  # maps the package instance and a set with all its dependencies
        names_map = {}  # maps all the package provided names to the package instance

        def _add_info(pkg: ArchPackage):
            try:
                srcinfo = self.aur_client.get_src_info(pkg.name)

                names_map[pkg.name] = pkg
                names = srcinfo.get('pkgname')

                if isinstance(names, list):
                    for n in names:
                        names_map[n] = pkg

                pkg_deps[pkg] = self.aur_client.extract_required_dependencies(srcinfo)
            except:
                pkg_deps[pkg] = None
                self.logger.warning("Could not retrieve dependencies for '{}'".format(pkg.name))
                traceback.print_exc()

        threads = []

        for pkg in aur_pkgs:
            t = Thread(target=_add_info, args=(pkg,), daemon=True)
            t.start()
            threads.append(t)

        self._fill_repo_pkgs_sort_data(repo_pkgs, pkg_deps, names_map)

        for t in threads:
            t.join()

        return self._sort_deps(pkg_deps, names_map)
