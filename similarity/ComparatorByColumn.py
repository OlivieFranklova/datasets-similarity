import warnings
from abc import ABC, abstractmethod
from statistics import mean

import numpy as np
import pandas as pd

from similarity.Comparator import DistanceFunction, Settings, cosine_sim, HausdorffDistanceMin
from similarity.DataFrameMetadata import DataFrameMetadata, KindMetadata, CategoricalMetadata
from similarity.Types import DataKind


class ComparatorType(ABC):
    def __init__(self, weight=1):
        self.weight = weight

    @abstractmethod
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        pass

    def _are_columns_null(self, column1, column2, message) -> tuple[bool, float]:
        """
        Check if columns are empty
        :param column1:
        :param column2:
        :param message:
        :return:  tuple of bool and float, if columns are empty return True
        """
        if len(column1) == 0 and len(column2) == 0:
            warnings.warn(f"Warning: {message} is not present in the dataframe.")
            return True, 0
        if (len(column1) == 0) != (len(column2) == 0):
            warnings.warn(f"Warning: {message} is not present in one of the dataframes.")
            return True, 1
        return False, 0


class TableComparator(ComparatorType):
    @abstractmethod
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str = 0,
                index2: int | str = 0) -> float:
        pass


class GeneralColumnComparator(ComparatorType):
    @abstractmethod
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        pass


class SpecificColumnComparator(ComparatorType):
    @abstractmethod
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        pass


class SizeComparator(TableComparator):
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str = 0,
                index2: int | str = 0) -> float:
        """
        Compare the size of the two dataframes. If sizes are the same distance is 0, else distance is 1 - % of max size.
        :param index1: in this case is not used
        :param index2: in this case it not used
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number in range <0, 1>
        """
        max_size = int(max(metadata1.size, metadata2.size))
        min_size = int(min(metadata1.size, metadata2.size))
        return 1 - (min_size / max_size)


class IncompleteColumnsComparator(GeneralColumnComparator):
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        """
        Compare if two columns are complete or incomplete. If both are complete,
         or both are incomplete distance is 0, else distance is 1.
        :param index2: name or id of  column in metadata2
        :param index1: name or id of column in metadata1
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number 0 or 1
        """
        return 0 if metadata1.column_incomplete[index1] == metadata2.column_incomplete[index2] else 1


class ColumnExactNamesComparator(GeneralColumnComparator):
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        """
        Compare if two columns have the same name. If both have the same name distance is 0, else distance is 1.
        :param index2: name or id of column in metadata2
        :param index1:  name or id of column in metadata1
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number 0 or 1
        """
        return 0 if metadata1.column_names_clean[index1] == metadata2.column_names_clean[index2] else 1


class ColumnNamesEmbeddingsComparator(GeneralColumnComparator):
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        """
        Compare if two columns have similar name. Computes cosine distance for embeddings.
        :param index2: name or id of column in metadata2
        :param index1:  name or id of column in metadata1
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number in range <0, 1> 0 exactly the same 1 completely different
        """
        if metadata1.column_name_embeddings == {} or metadata2.column_name_embeddings == {}:
            warnings.warn("Warning: column name embedding is not computed")
            return np.nan
        return 1 - cosine_sim(metadata1.column_name_embeddings[index1], metadata2.column_name_embeddings[index2])


class ColumnEmbeddingsComparator(GeneralColumnComparator):
    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        """
        Compare embeddings for two columns. Computes cosine distance for embeddings.
        :param index2: name or id of column in metadata2
        :param index1:  name or id of column in metadata1
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number in range <0, 1> 0 exactly the same 1 completely different
        """
        if (metadata1.column_embeddings == {} or metadata2.column_embeddings == {} or
                index1 not in metadata1.column_embeddings or index2 not in metadata2.column_embeddings):
            warnings.warn("Warning: column embedding is not computed")
            return np.nan
        return 1 - cosine_sim(metadata1.column_embeddings[index1], metadata2.column_embeddings[index2])


class ColumnKindComparator(SpecificColumnComparator):
    def __init__(self, compare_kind=None, weight: dict[DataKind, int] = None):
        super().__init__(weight=1)
        if compare_kind is None:
            self.compare_kind = [DataKind.BOOL, DataKind.ID, DataKind.CATEGORICAL, DataKind.CONSTANT]
        else:
            self.compare_kind = compare_kind
        if weight is None:
            self.kind_weight = {DataKind.BOOL: 1, DataKind.ID: 1, DataKind.CATEGORICAL: 1, DataKind.CONSTANT: 1}
        else:
            self.kind_weight = weight

    def compute_embeddings_distance(self, embeddings1, embeddings2) -> float:
        """
        Creates table of distances between embeddings for each row  and computes mean of row and column minimums then pick max.
        :param embeddings1: values for column1
        :param embeddings2: values for column2
        :return: float from 0 to 1
        """
        res = pd.DataFrame()
        row_mins = []
        for id1, embed1 in enumerate(embeddings1.items()):
            for id2, embed2 in enumerate(embeddings2.items()):
                res.loc[id1, id2] = 1 - cosine_sim(embed1, embed2)
            row_mins.append(min(res[id1]))
        column_mins = []
        for _, column in res.items():
            column_mins.append(min(column))
        return max([mean(row_mins), mean(column_mins)])  # todo vysvetlit v textu

    def compare_bools(self, metadata1: KindMetadata, metadata2: KindMetadata) -> float:
        """
        Compare two boolean columns. Compare if they have the same distribution of True and False values.
        Compare if they contain nulls.
        Compare embeddings of values.
        Make an average of these values.
        :param metadata1: for column1
        :param metadata2: for column2
        :return: float number in range <0, 1>
        """
        nulls = 0 if metadata1.nulls == metadata2.nulls else 1
        distr = abs(
            metadata1.distribution[0] / metadata1.distribution[1] - metadata2.distribution[0] / metadata2.distribution[
                1])
        if metadata1.value_embeddings is None or metadata2.value_embeddings is None:
            return (nulls + distr) / 2
        return (nulls + distr + self.compute_embeddings_distance(metadata1.value_embeddings,
                                                                 metadata2.value_embeddings)) / 3

    def compare_categoricals(self, metadata1: CategoricalMetadata, metadata2: CategoricalMetadata) -> float:
        """
        Compare two categorical columns. Compare if they contain nulls.
        Compare embeddings of values.
        Make an average of these values.
        :param metadata1: for column1
        :param metadata2: for column2
        :return: float number in range <0, 1>
        """
        value_re = self.compute_embeddings_distance(metadata1.category_embedding, metadata2.category_embedding)
        count1 = metadata1.count_categories
        count2 = metadata2.count_categories
        count_re = count1 / count2 if count1 < count2 else count2 / count1
        # todo compare categories_with_count for metadata1 and metadata2
        # firstly normalize dictionary categories_with_count then
        # compare the difference between the two dictionaries
        return (value_re + count_re) / 2

    def compare_constants(self, metadata1: KindMetadata, metadata2: KindMetadata) -> float:
        """
        Compare two constant columns. Compare if they contain nulls.
        Compare embeddings of values.
        Make an average of these values.
        :param metadata1: for column1
        :param metadata2: for column2
        :return: float number in range <0, 1>
        """
        nulls = 0 if metadata1.nulls == metadata2.nulls else 1
        if metadata1.value_embeddings is None or metadata2.value_embeddings is None:
            value = 0 if metadata1.value == metadata2.value else 1
        else:
            value = 1 - cosine_sim(metadata1.value_embeddings, metadata2.value_embeddings)
        # if nulls are equal and exist
        if nulls == 0 and metadata1.nulls:
            ratio1 = metadata1.distribution[0] / metadata1.distribution[1]
            ratio2 = metadata2.distribution[0] / metadata2.distribution[1]
            nulls = abs(ratio1 - ratio2)  # compute difference between distribution
        return (nulls + value) / 2

    def compare_ids(self, metadata1: KindMetadata, metadata2: KindMetadata) -> float:
        """
        Compare two id columns. Compare if they contain nulls.
        Compare embeddings of values.
        Compare ratio of max length.
        Make an average of these values.
        :return: float number in range <0, 1>
        """
        embeddings1_longest = metadata1.longest_embeddings
        embeddings2_longest = metadata2.longest_embeddings
        embeddings1_shortest = metadata1.shortest_embeddings
        embeddings2_shortest = metadata2.shortest_embeddings

        if embeddings1_longest is not None and embeddings2_longest is not None:
            value_long_re = 1 - cosine_sim(embeddings1_longest, embeddings2_longest)
        else:
            value_long_re = 0 if metadata1.longest == metadata2.longest else 1
        if embeddings1_shortest is not None and embeddings2_shortest is not None:
            value_short_re = 1 - cosine_sim(embeddings1_shortest, embeddings2_shortest)
        else:
            value_short_re = 0 if metadata1.shortest == metadata2.shortest else 1

        nulls_re = 0 if metadata1.nulls == metadata2.nulls else 1
        ratio_max_re = abs(metadata1.ratio_max_length - metadata2.ratio_max_length)
        return (value_short_re + value_long_re + nulls_re + ratio_max_re) / 4

    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata, index1: int | str,
                index2: int | str) -> float:
        """
        Compare if two columns have the same kind. If both have the same kind distance is 0, else distance is 1.
        :param index2: name or id of column in metadata2
        :param index1:  name or id of column in metadata1
        :param metadata1: first dataframe metadata
        :param metadata2: second dataframe metadata
        :return: float number 0 or 1

        data_kinds = [DataKind.BOOL, DataKind.ID, DataKind.CATEGORICAL, DataKind.CONSTANT]
        compare_methods = [self.compare_bools, self.compare_ids, self.compare_categoricals, self.compare_constants]

        for kind, method in zip(data_kinds, compare_methods):
            if kind in self.compare_kind:
                if index1 in metadata1.column_kind[kind] and index2 in metadata2.column_kind[kind]:
                    return method()
                if index1 in metadata1.column_kind[kind] or index2 in metadata2.column_kind[kind]:
                    return 1
        return np.nan

        """
        if DataKind.BOOL in self.compare_kind:
            if index1 in metadata1.column_kind[DataKind.BOOL] and index2 in metadata2.column_kind[DataKind.BOOL]:
                return self.compare_bools(metadata1.kind_metadata[index1], metadata2.kind_metadata[index2])
            are_nulls = self._are_columns_null(metadata1.column_kind[DataKind.BOOL], metadata2.column_kind[DataKind.BOOL],"Boolean column")
        if DataKind.ID in self.compare_kind:
            if index1 in metadata1.column_kind[DataKind.ID] and index2 in metadata2.column_kind[DataKind.ID]:
                return self.compare_ids(metadata1.kind_metadata[index1], metadata2.kind_metadata[index2])
            are_nulls = self._are_columns_null(metadata1.column_kind[DataKind.ID], metadata2.column_kind[DataKind.ID],"ID column")
        if DataKind.CATEGORICAL in self.compare_kind:
            if index1 in metadata1.column_kind[DataKind.CATEGORICAL] and index2 in metadata2.column_kind[
                DataKind.CATEGORICAL]:
                return self.compare_categoricals(metadata1.categorical_metadata[index1], metadata2.categorical_metadata[index2])
            are_nulls = self._are_columns_null(metadata1.column_kind[DataKind.CATEGORICAL], metadata2.column_kind[DataKind.CATEGORICAL],"Categorical column")
        if DataKind.CONSTANT in self.compare_kind:
            if index1 in metadata1.column_kind[DataKind.CONSTANT] and index2 in metadata2.column_kind[
                DataKind.CONSTANT]:
                return self.compare_constants(metadata1.kind_metadata[index1], metadata2.kind_metadata[index2])
            are_nulls = self._are_columns_null(metadata1.column_kind[DataKind.CONSTANT], metadata2.column_kind[DataKind.CONSTANT],"Constant column")

        if are_nulls[0]:
            return are_nulls[1]
        return np.nan

class ComparatorByColumn:
    def __init__(self):
        self.comparator_type: list[ComparatorType] = []
        self.table_comparators: list[TableComparator] = []
        self.settings: set[Settings] = set()
        self.distance_function = HausdorffDistanceMin()

    def set_distance_function(self, distance_function: DistanceFunction) -> 'ComparatorByColumn':
        self.distance_function = distance_function
        return self

    def set_settings(self, settings: list) -> 'ComparatorByColumn':
        self.settings = settings
        return self

    def add_settings(self, setting) -> 'ComparatorByColumn':
        self.settings.add(setting)
        return self

    def add_comparator_type(self, comparator: ComparatorType) -> 'ComparatorByColumn':
        # todo if comparator contains type and kind comparator change it to kind_and_tyep_comparator
        if isinstance(comparator, TableComparator):
            self.table_comparators.append(comparator)
        else:
            self.comparator_type.append(comparator)
        return self

    def weightwed_avg(self, distances: list[tuple[float, int]]) -> float:
        """
        Compute weighted average of distances
        :param distances: list of tuples (distance, weight)
        :return: weighted average
        """
        ##todo pokud je neco z toho none
        sum_weight = sum([weight for _, weight in distances])
        return sum([distance * weight / sum_weight for distance, weight in distances])

    def compare(self, metadata1: DataFrameMetadata, metadata2: DataFrameMetadata):
        table_distances = []
        distances = pd.DataFrame()
        for comparator in self.table_comparators:
            table_distances.append(comparator.compare(metadata1, metadata2))
        if self.comparator_type:
            for column1 in metadata1.column_names:
                for column2 in metadata2.column_names:
                    comparators_distances = []
                    for comparator in self.comparator_type:
                        comparators_distances.append((comparator.compare(metadata1, metadata2, column1, column2),
                                                      comparator.weight))
                    distances.loc[column1, column2] = self.weightwed_avg(comparators_distances)
            res = self.distance_function.compute(distances)
            res = res * res
        else:
            res = 0
        if table_distances:
            for dist in table_distances:
                res += dist * dist
        return np.sqrt(res)


